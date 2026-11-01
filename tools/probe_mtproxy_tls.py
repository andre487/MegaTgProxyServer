"""Live regression check: legacy and modern FakeTLS plus encrypted MTProto."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time

from ansible.parsing.vault import VaultLib, VaultSecret
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]


def u16(value):
    return struct.pack('>H', value)


def extension(kind, data):
    return u16(kind) + u16(len(data)) + data


def client_hello(domain, key, modern):
    domain = domain.encode('idna')
    sni = u16(len(domain) + 3) + b'\0' + u16(len(domain)) + domain
    share = (u16(0x11ec) + u16(1216) + secrets.token_bytes(1216)) if modern else (u16(29) + u16(32) + secrets.token_bytes(32))
    extensions = extension(0, sni) + extension(43, b'\x02\x03\x04') + extension(51, u16(len(share)) + share)
    ciphers = bytes.fromhex('0a0a13021301') if modern else bytes.fromhex('1301')
    prefix = b'\x03\x03' + bytes(32) + b'\x20' + secrets.token_bytes(32) + u16(len(ciphers)) + ciphers + b'\x01\x00'
    if not modern:
        extensions += extension(21, bytes(517 - 9 - len(prefix) - 2 - len(extensions) - 4))
    body = prefix + u16(len(extensions)) + extensions
    handshake = b'\x01' + len(body).to_bytes(3, 'big') + body
    packet = bytearray(b'\x16\x03\x01' + u16(len(handshake)) + handshake)
    random = bytearray(hmac.digest(key, packet, 'sha256'))
    timestamp = struct.pack('<I', int(time.time()))
    for i in range(4):
        random[28+i] ^= timestamp[i]
    packet[11:43] = random
    return packet, bytes(random)


def probe(address, port, domain, key, modern):
    hello, random = client_hello(domain, key, modern)
    with socket.create_connection((address, port), timeout=15) as connection:
        def read(size):
            data = b''
            while len(data) < size:
                chunk = connection.recv(size - len(data))
                if not chunk:
                    raise RuntimeError('Unexpected EOF')
                data += chunk
            return data

        def record():
            header = read(5)
            return header, read(int.from_bytes(header[3:5], 'big'))

        connection.sendall(hello)
        reply = bytearray()
        for _ in range(3):
            header, payload = record()
            reply += header + payload
        digest = bytes(reply[11:43])
        reply[11:43] = bytes(32)
        assert hmac.compare_digest(digest, hmac.digest(key, random + reply, 'sha256')), 'FakeTLS HMAC mismatch: server rejected ClientHello'
        assert reply[76:78] == (b'\x13\x02' if modern else b'\x13\x01'), 'Incorrect selected cipher suite'
        assert reply[44:76] == hello[44:76], 'Incorrect session ID'

        header = bytearray(secrets.token_bytes(64))
        header[0] = 0x89
        header[56:60] = b'\xdd' * 4
        header[60:62] = struct.pack('<h', 2)
        reverse = bytes(header[8:56])[::-1]
        encrypt = Cipher(algorithms.AES(hashlib.sha256(bytes(header[8:40]) + key).digest()), modes.CTR(bytes(header[40:56]))).encryptor()
        decrypt = Cipher(algorithms.AES(hashlib.sha256(reverse[:32] + key).digest()), modes.CTR(reverse[32:])).decryptor()
        encrypted = encrypt.update(bytes(header))
        header[56:64] = encrypted[56:64]
        nonce = secrets.token_bytes(16)
        body = struct.pack('<I', 0xbe7e8ef1) + nonce
        message = struct.pack('<QQI', 0, int(time.time()*2**32) & ~3, len(body)) + body + secrets.token_bytes(8)
        payload = bytes(header) + encrypt.update(struct.pack('<I', len(message)) + message)
        connection.sendall(b'\x14\x03\x03\x00\x01\x01\x17\x03\x03' + u16(len(payload)) + payload)
        response = b''
        while len(response) < 4 or len(response) < 4 + int.from_bytes(response[:4], 'little'):
            header, payload = record()
            if header[0] == 23:
                response += decrypt.update(payload)
            if len(response) >= 4:
                assert int.from_bytes(response[:4], 'little') <= 1048576, 'Oversized response'
        response = response[4:]
        assert response[:8] == bytes(8) and response[20:24] == struct.pack('<I', 0x05162463), 'Expected MTProto resPQ'
        assert response[24:40] == nonce, 'MTProto nonce mismatch'
    print(f'{address}:{port}: {"modern ML-KEM/GREASE" if modern else "legacy"} ClientHello ({len(hello)} bytes), FakeTLS and MTProto OK')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='Backend inventory name containing the FakeTLS secret')
    parser.add_argument('address', help='Public address to test, directly or through jump')
    parser.add_argument('--inventory', type=Path)
    args = parser.parse_args()
    args.inventory = args.inventory or Path((ROOT/'inventory-path').read_text().strip() if (ROOT/'inventory-path').exists() else 'inventory.yml')
    inventory = json.loads(subprocess.check_output([sys.executable, '-m', 'ansible.cli.inventory', '-i', str(args.inventory.expanduser()), '--list'], cwd=ROOT))
    host = inventory['_meta']['hostvars'][args.host]
    secret = host['tg_secret']
    if isinstance(secret, dict):
        password = Path(os.environ['ANSIBLE_VAULT_PASSWORD_FILE']).expanduser().read_bytes().strip()
        secret = VaultLib([('default', VaultSecret(password))]).decrypt(secret['__ansible_vault']).decode()
    for modern in [False, True]:
        probe(args.address, int(host['tg_port']), host['tg_domain'], bytes.fromhex(secret), modern)
