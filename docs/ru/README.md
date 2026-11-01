# Руководство MegaTgProxyServer

[Описание проекта](../../README.md) · [English](../en/README.md)

[Подготовка](#подготовка) · [Команды](#команды) · [Inventory](#inventory) ·
[Секреты](#секреты) · [SSH-выход](#ssh-выход) · [Система](#система) ·
[Хуки](#хуки) · [Эксплуатация](#эксплуатация) · [Диагностика](#диагностика)

## Подготовка

На управляющей macOS/Linux нужны Git, Python 3.12+, uv и OpenSSH. На Debian/Ubuntu
уже должен существовать непривилегированный администратор с SSH-ключом и sudo.
Укажите его в ansible_user и tg_admin.user; bootstrap через root отсутствует.
Если sudo требует пароль, передайте --ask-become-pass. В локальном checkout:

```sh
./mega-tg-proxy deps
umask 077
mkdir -p ~/.config/mega-tg-proxy
cp inventory.example.yml ~/.config/mega-tg-proxy/inventory.yml
printf '%s\n' ~/.config/mega-tg-proxy/inventory.yml > inventory-path
```

Выберите пример для своего движка и выхода, замените заглушки. deps подготавливает
окружение из uv.lock и показывает коллекции Ansible; серверы не меняет. Другие
команды скрипта тоже автоматически подготавливают окружение.

Для **нового** inventory один раз создайте файл пароля в приватном редакторе:
введите стойкий пароль Vault одной строкой. Не перезаписывайте пароль существующего inventory.

```sh
$EDITOR ~/.config/mega-tg-proxy/vault-password
chmod 600 ~/.config/mega-tg-proxy/vault-password
export ANSIBLE_VAULT_PASSWORD_FILE="$HOME/.config/mega-tg-proxy/vault-password"
```

Сохраните пароль отдельно: без него зашифрованные значения не восстановить.
Для существующего inventory используйте его исходный пароль. Если переменная
не задана и inventory содержит inline !vault, Ansible запросит пароль интерактивно.

## Команды

| Команда | Назначение |
|---|---|
| `deps` | Подготовить локальное окружение и показать коллекции |
| `plan` | Check mode; запуск служб и скачивание protocol key пропускаются |
| `apply --verify` | Применить → проверить → хуки; остановиться при ошибке |
| `apply` | Применить и запустить хуки без верификации |
| `verify` | Проверить контейнеры, публичные TCP-порты, метрики MTG и SSH/SOCKS5-выход |
| `configs` | Напечатать клиентские ссылки с секретами |
| `secret` | Напечатать новый tg_secret в Vault; inventory не изменяется |
| `check` | Локальные тесты и проверка Ansible-рендера |

--inventory PATH, --limit HOST и --no-hooks допускаются до или после команды.
Без --inventory читается inventory-path, затем используется inventory.yml.
Относительные пути разрешаются от корня репозитория. --verify допустим только с apply.
Дополнительные аргументы передаются Ansible. Фильтры --tags/--skip-tags/--start-at-task
при apply не ограничивают последующий verify; остальные аргументы и --limit сохраняются.
У ролей сейчас нет тегов раскатки: --tags proxy не выбирает роль автоматически.

## Inventory

Используется native Ansible YAML: хосты в all.children.tg_proxies.hosts, общие значения
в vars группы. Рабочий файл храните вне публичного репозитория. inventory-path,
.hooks, .generated, .secrets и inventory.yml игнорируются Git.

| Переменная | Смысл / значение по умолчанию |
|---|---|
| `ansible_host`, `ansible_user`, `ansible_port` | Адрес управления, существующий администратор, SSH-порт (22) |
| `ansible_ssh_private_key_file` | Необязательный локальный путь к административному приватному ключу |
| `tg_admin.user`, `tg_admin.public_key` | Управляемый непривилегированный администратор и публичный ключ |
| `tg_endpoint` | Адрес в клиентских ссылках; по умолчанию ansible_host |
| `tg_port` | Публичный TCP-порт; задайте явно, обычно 443 |
| `tg_engine` | mtg или mtproxy |
| `tg_mode` | faketls для MTG, classic для официального MTProxy |
| `tg_secret` | Обязательный Vault-ключ: 32 hex-символа |
| `tg_domain` | SNI-домен FakeTLS; при импорте сохраняется исходный |
| `tg_egress` | direct или ssh для MTG |
| `tg_image` | Для MTG по умолчанию nineseconds/mtg:2.2.8, для MTProxy telegrammessenger/proxy:latest |
| `tg_container_name` | Задайте явно mtg-proxy или mtproto-proxy; используется и в verify |
| `tg_publish_ipv6` | Дополнительно публиковать прокси на IPv6; по умолчанию false |
| `tg_mtg_config` | Полный TOML MTG с заглушкой __MEGATG_SECRET__ вместо секрета |
| `tg_workers` | Число worker официального MTProxy; по умолчанию 2 |
| `tg_mtproxy_volume` | Volume официального MTProxy; по умолчанию megatg-mtproxy-data |
| `tg_unattended_upgrades` | Задайте явно; true включает периодические автообновления |

Задавайте tg_engine, tg_mode, tg_egress, tg_port и tg_container_name явно: отдельные
verify/configs не загружают role defaults. Для FakeTLS нужен ASCII/IDNA hostname.
Полный tg_mtg_config должен слушать 3128, отдавать метрики на 3129 и соответствовать
выбранному выходу. Секрет подставляется вместо __MEGATG_SECRET__.

## Секреты

После настройки ANSIBLE_VAULT_PASSWORD_FILE генерируйте ключ локально:

```sh
./mega-tg-proxy secret --mode faketls --domain www.example.com
# Или для официального MTProxy:
./mega-tg-proxy secret --mode classic
```

Вставьте зашифрованный YAML в нужный хост. tg_mode/tg_domain задаются отдельно:
--domain проверяет вход генератора, но не сохраняет настройку. Клиентский секрет
FakeTLS — `ee + 16-байтовый ключ + hex(domain)`; официальный MTProxy использует classic-ключ.
Apply не генерирует и не ротирует клиентские ключи. Смена ключа или FakeTLS-домена
меняет клиентскую ссылку; configs печатает её только по явному запросу.

Шифрование **существующего** ключа без записи в shell history:

```sh
./.venv/bin/ansible-vault encrypt_string --prompt --name tg_secret
# Приватный ключ SSH из файла:
./.venv/bin/ansible-vault encrypt_string --stdin-name tg_ssh_private_key < /private/path/id_ed25519
```

Вставьте зашифрованный результат в inventory. Открытые ключи-секреты и вывод configs
не публикуются. Служебный protocol key Telegram не связан с клиентским секретом.

## SSH-выход

Используйте [inventory.ssh.example.yml](../../inventory.ssh.example.yml). MegaProxyServer
может управлять forwarding-аккаунтом exit; этот проект настраивает клиентский туннель.
Задайте tg_ssh_host/port/user, tg_ssh_private_key в Vault и tg_ssh_known_hosts.
Host key проверяется по доверенному каналу; для нестандартного порта нужна запись
`[hostname]:port`. StrictHostKeyChecking включён.

Явно задайте tg_network/bridge/subnet/gateway и tg_ssh_socks_port. SSH поднимает SOCKS
на шлюзе выделенной Docker-сети; UFW разрешает доступ из её подсети через её bridge.
Изменение ключа, known_hosts или unit перезапускает mtg-ssh-egress. Переключение на
прямой выход не удаляет прежнюю службу и сеть автоматически.

## Система

Управляются пакеты исполнения/защиты, Docker, синхронизация времени, fail2ban для SSH,
UFW, unattended-upgrades и ограничения журналов. Docker CE сохраняется, на новых хостах
ставится docker.io. Docker-логи ротируются по 10 MB × 3, journald ограничен 500 MB.
Авторебут отключён; источники обновлений задаёт дистрибутив. Login notifier не устанавливается.

Администратор получает sudo без пароля; его authorized_keys заменяется указанным
ключом, root/password SSH login отключается. При ошибке проверки SSH-политики
восстанавливается прежняя политика; общего отката раскатки нет.
UFW разрешает SSH, прокси и при необходимости внутренний SOCKS. Чужие allow-правила
сохраняются. Docker publications обходят UFW INPUT; другие контейнеры проверяйте отдельно.

## Хуки

После успеха: .hooks/post-config-change, затем исполняемые файлы
.hooks/post-config-change.d в порядке имён. С --verify они идут после проверки.
Ошибка останавливает дальнейшие шаги и возвращает ненулевой код, без отката
применённых изменений. Рабочий каталог — корень репозитория. Окружение:

| Переменная | Значение |
|---|---|
| `MEGATG_ROOT` | Абсолютный путь репозитория |
| `MEGATG_EVENT` | post-config-change |
| `MEGATG_INVENTORY`, `MEGATG_ANSIBLE_INVENTORY` | Абсолютный путь выбранного native inventory |

Хуки получают **весь inventory**, даже с --limit; нужную фильтрацию реализуют сами.
--no-hooks отключает их, но не verify.

```sh
mkdir -p .hooks
cp examples/post-config-change .hooks/post-config-change
chmod 700 .hooks/post-config-change
```

Пример вызывает px-manager/tools/deploy.sh; путь checkout меняется через PX_MANAGER_REPO.
TG-inventory передаётся в MEGAPROXY_INVENTORY. Нужна поддержка этого формата в px-manager;
пока она не установлена, используйте --no-hooks. Локальные хуки не коммитятся.

## Эксплуатация

До раскатки сохраните приватный inventory/пароль Vault, текущие image digest и имена
volume. При импорте сохраняйте ключи и FakeTLS-домены; у контейнера без persistent
storage извлеките ключ до пересоздания. Разовые миграционные скрипты/плейбуки
должны оставаться вне продового репозитория.

```sh
./mega-tg-proxy plan --limit example
./mega-tg-proxy apply --limit example --verify --no-hooks
./mega-tg-proxy configs --limit example
```

По умолчанию apply параллельный; применяйте по одному хосту, сохраняя альтернативы.
Пересоздание контейнера обрывает сессии. verify проверяет готовность, а не MTProto-сессию:
перед следующим хостом проверьте сообщения/медиа в Telegram из проблемной сети.
При ошибке verify изменения остаются применёнными. Для восстановления верните прежние
значения inventory и pinned image, повторите apply на одном хосте и verify. Это не
откатывает все системные изменения и не восстанавливает удалённые данные: нужны
доступ к консоли и резервные копии.

Для обновлений явно меняйте версию/digest. pull: missing не обновляет уже скачанный
mutable tag; предпочтителен digest. Официальный MTProxy получает backend list при
старте; роль скачивает server protocol key по HTTPS с проверкой сертификата.
Каждым контейнером должен управлять один проект.

## Диагностика

На сервере используйте docker ps, ss -lntp и проверки настроенных служб:

```sh
sudo systemctl status mtg-ssh-egress
sudo journalctl -u mtg-ssh-egress --since '10 minutes ago'
curl --fail http://127.0.0.1:3129/metrics
```

Если порт недоступен — проверьте DNS, firewall провайдера, UFW и mapping Docker.
Если зависают медиа — сравните клиентский/серверный захват и TCP retransmissions.
Если MTG не принимает клиентов — очередь listener и лимиты процесса. Startup-логи
официального MTProxy могут содержать секрет: удаляйте его перед публикацией;
packet capture храните приватно.

Локальные проверки (без полноценной серверной/Telegram-сессии):

```sh
./mega-tg-proxy check
./mega-tg-proxy --inventory inventory.example.yml plan --syntax-check
./mega-tg-proxy --inventory inventory.ssh.example.yml plan --syntax-check
./mega-tg-proxy --inventory inventory.mtproxy.example.yml plan --syntax-check
```
