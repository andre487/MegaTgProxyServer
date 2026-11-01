# Руководство MegaTgProxyServer

<p align="center">
  <img src="../assets/icon-radius.svg" width="160" alt="MPX — MegaTgProxyServer">
</p>

[Описание проекта](../../README.md) · [English](../en/README.md)

[Подготовка](#подготовка) · [Команды](#команды) · [Inventory](#inventory) ·
[Секреты](#секреты) · [SSH-выход](#ssh-выход) · [Система](#система) ·
[Хуки](#хуки) · [Эксплуатация](#эксплуатация) · [Диагностика](#диагностика)

## Подготовка

На управляющей macOS/Linux нужны Git, Python 3.12+, uv и OpenSSH. На Debian/Ubuntu
нужен непривилегированный администратор с SSH-ключом и sudo.
На новой ноде создайте его командой `bootstrap` (см. ниже).
Укажите его в ansible_user и tg_admin.user.
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
| `bootstrap` | Создать администратора, проверить SSH/sudo и применить SSH-политику; требует точные имена в --limit |
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
Доступны теги `jump`, `tunnel_users` и `cleanup`; очистка также помечена `always`.
Тега `proxy` нет. Фильтрация задач не отключает автоматическую очистку.

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
| `tg_mode` | faketls для MTG; classic или faketls для официального MTProxy |
| `tg_secret` | Обязательный Vault-ключ: 32 hex-символа |
| `tg_domain` | SNI-домен FakeTLS; при импорте сохраняется исходный |
| `tg_egress` | direct или ssh (оба движка) |
| `tg_image` | Для MTG по умолчанию nineseconds/mtg:2.2.8, для MTProxy megatg/mtproxy:<commit>-minimal |
| `tg_container_name` | Задайте явно mtg-proxy или mtproto-proxy; используется и в verify |
| `tg_publish_ipv6` | Дополнительно публиковать прокси на IPv6; по умолчанию false |
| `tg_mtg_template` | Имя шаблона MTG; по умолчанию mtg.toml.j2, профиль с тюнингом — mtg-tuned.toml.j2 |
| `tg_workers` | Число worker официального MTProxy; по умолчанию 2 |
| `tg_mtproxy_volume` | Volume официального MTProxy; по умолчанию megatg-mtproxy-data |
| `tg_unattended_upgrades` | Задайте явно; true включает периодические автообновления |

Задавайте tg_engine, tg_mode, tg_egress, tg_port и tg_container_name явно: отдельные
verify/configs не загружают role defaults. Для FakeTLS нужен ASCII/IDNA hostname.
Конфиги хранятся только в `templates/`, не в inventory, defaults или тасках.
Шаблон MTG получает `tg_secret_full` и строит выход из `tg_egress` и SSH-параметров.
Для профиля с тюнингом доступны параметры `tg_mtg_debug`, `tg_mtg_prefer_ip`,
`tg_mtg_auto_update`, `tg_mtg_http_timeout` и `tg_mtg_idle_timeout`.
Общие версии образов и commit заданы в defaults; inventory содержит только
индивидуальные переопределения и детали инфраструктуры.

## Секреты

После настройки ANSIBLE_VAULT_PASSWORD_FILE генерируйте ключ локально:

```sh
./mega-tg-proxy secret --mode faketls --domain www.example.com
# Или для официального MTProxy:
./mega-tg-proxy secret --mode classic
```

Вставьте зашифрованный YAML в нужный хост. tg_mode/tg_domain задаются отдельно:
--domain проверяет вход генератора, но не сохраняет настройку. Клиентский секрет
FakeTLS — `ee + 16-байтовый ключ + hex(domain)` для обоих движков. В `tg_secret`
всегда хранится только исходный 16-байтовый ключ, без префикса и домена.
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
Авторебут отключён; источники обновлений задаёт дистрибутив.

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
| `MEGATG_LINKS_FILE` | Абсолютный путь к `.generated/links.txt`, только ссылки выбранных хостов |
| `MEGATG_LIMIT` | Значение `--limit` или пустая строка |
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

Apply выполняется параллельно по хостам с обычной стратегией Ansible (по умолчанию до 5 forks).
Число параллельных процессов можно задать через `--forks N` (`-f N`).
Пересоздание контейнера обрывает сессии. verify проверяет готовность, а не MTProto-сессию:
перед следующим хостом проверьте сообщения/медиа в Telegram из проблемной сети.
При ошибке verify изменения остаются применёнными. Для восстановления верните прежние
значения inventory и прежнюю версию образа/исходников, повторите apply и verify.
Удалённый очисткой образ потребуется заново скачать или собрать. Это не
откатывает все системные изменения и не восстанавливает удалённые данные: нужны
доступ к консоли и резервные копии.

Для обновления MTG меняйте `tg_image` (версию/digest); `pull: missing` не обновляет
уже скачанный mutable tag. Для официального MTProxy меняйте `tg_mtproxy_source_ref`:
роль соберёт новую версию на сервере. Backend list и protocol key скачивает Ansible
при раскатке по HTTPS с проверкой сертификата.
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

Для MTProxy с SSH-выходом задайте `tg_engine: mtproxy`, `tg_egress: ssh` и
SSH-параметры из `inventory.ssh.example.yml`. TCP перенаправляется через redsocks
в SSH SOCKS5; IPv6 контейнера отключён. Сеть и bridge должны быть выделенными.
Проверяйте фактический выходной маршрут на Linux перед использованием.

## Bootstrap и входной jump

`./mega-tg-proxy --limit HOST bootstrap` использует ту же двухфазную схему,
что MegaProxyServer: account → свежая проверка SSH-ключа/sudo → policy → повторная
проверка. В host-specific `tg_admin` задайте `user`, `public_key`, `private_key_file`,
`bootstrap_user`, `bootstrap_auth: password` (или `key`) и при необходимости
`bootstrap_private_key_file`. Для пароля можно передать `--bootstrap-password-file`;
иначе он запрашивается скрыто. После успеха bootstrap-поля удаляются из inventory.

`tg_tunnel_users` — список `{name, port, public_keys}`. Пользователи могут открывать
только SSH local forwarding к `127.0.0.1:port`, без shell, PTY, remote forwarding
или sudo. Ключи заменяются списком из inventory. Тег `tunnel_users` позволяет
настроить только эти учётные записи без перезапуска прокси.

`tg_node_role: jump` заменяет локальный прокси HAProxy на том же `tg_port`.
Задайте `tg_jump_domain`, Vault `tg_jump_private_key`, проверенные
`tg_jump_known_hosts` и маршруты `tg_jump_tunnels`, включая `faketls`/`classic`
с полями `host`, `user`, `local_port`, `remote_port`, необязательно `ssh_port`.
Совпадающий SNI направляется в faketls, неизвестный TLS отклоняется, соединения
без TLS идут в classic после ожидания до 3 секунд. SSH-туннели слушают только
localhost. Перед остановкой прежнего контейнера проверяется TLS-путь к FakeTLS
backend. После успешного переключения очистка удаляет старый остановленный контейнер.

`configs --limit JUMP` печатает готовые ссылки FakeTLS и classic с секретами
соответствующих backend. В каждом маршруте укажите `inventory_host` — имя backend в inventory,
и уникальный `endpoint` — публичный домен/IP для ссылки этого маршрута.

Перед запуском настроенного hook после успешного apply (и verify, если задан)
всегда генерируется `.generated/links.txt` с правами 0600, по одной ссылке на строку.
При ошибке генерации hook не запускается. Без `--limit` экспортируются все хосты;
с лимитом — только выбранные. `--no-hooks` отключает автоматическую генерацию.
Отдельная выгрузка: `./mega-tg-proxy --limit jump configs --output .generated/links.txt`.

Для stdout используйте `configs --output -` или `configs --output /dev/stdout`.
В stdout попадают только ссылки; сообщения Ansible отправляются в stderr.

В `tg_jump_tunnels` поле `endpoint` задаёт публичный адрес конкретного маршрута:
например, `faketls → jump-tls.example.com`, `classic → jump-classic.example.com`.
Это адреса в клиентских ссылках одного jump, а не отдельные конфигурации сервера.
Параметры секрета и FakeTLS берутся из соответствующего backend без изменений.
CLI предупреждает в stderr, если сгенерированные ссылки используют одинаковый
публичный домен или IP, включая разные маршруты одного jump. Регистр и завершающая
точка не учитываются. FakeTLS-домен для этой проверки не используется.

Официальный MTProxy поддерживает `tg_mode: faketls`: роль загружает backend list,
монтирует собственный startup и вызывает бинарник с `-D tg_domain`, без `-M`.
`tg_public_ip` задаёт внешний IPv4 для NAT (по умолчанию адрес основного интерфейса).
Если FakeTLS-домен указывает на сам сервер, задайте `tg_mtproxy_fronting_ip` —
внешний TLS-адрес для fallback: Docker переопределит разрешение домена только
внутри контейнера, сохранив SNI. Это предотвращает соединения MTProxy с самим собой.

Для дополнительных TLS-маршрутов jump добавляйте элементы `tg_jump_tunnels` с
уникальными `name`, `local_port`, `sni` и публичным `endpoint`. Маршрут `classic`
остаётся default для трафика без TLS. Конфигурация HAProxy обновляется через reload.

Официальный MTProxy по умолчанию собирается из закреплённого commit; для обновления
задайте `tg_mtproxy_source_ref` (полный 40-символьный commit). Имя локального
образа формируется автоматически. Docker Hub `telegrammessenger/proxy:latest` содержит
старый бинарник и не подходит для современных расширенных FakeTLS ClientHello.
Проверка обоих форматов с реальным MTProto-обменом (секреты не печатает):
`uv run python tools/probe_mtproxy_tls.py tls_backend edge-tls.example.com`.

Все официальные MTProxy собираются на целевых нодах из `tg_mtproxy_source_ref`
(по умолчанию закреплённый commit). Сборочный stage содержит компилятор и headers;
runtime — `scratch`, бинарник, его динамические библиотеки, статический BusyBox и
минимальные passwd/group/NSS-файлы. Curl, apt, компилятора и headers в runtime нет.
Backend list и protocol key скачивает Ansible на хосте; startup общий для classic
и FakeTLS, без смены клиентских секретов и портов.

После каждой раскатки, включая запуск с тегами, выполняется роль `docker_cleanup`.
Сначала проверяются контейнер и listener. Затем удаляются неиспользуемые старые
образы этого проекта, остановленные контейнеры и пустые сети с метками
`io.megatg.managed=true`/`io.megatg.build=true`. Старые сборочные слои до введения
меток распознаются по URL официального исходника в Docker history. Образ,
используемый любым контейнером (включая остановленный), не удаляется принудительно.
Постоянные volumes и общие образы других приложений не очищаются.
На jump также убираются прежний остановленный MTG, старый SOCKS unit и пустая сеть.
`--tags cleanup` запускает только очистку; check mode не удаляет ресурсы.

Порядок ссылок задаётся списком `tg_links_order` в `tg_proxies.vars`: перечислите
точные публичные домены/IP из ссылок в нужном порядке. Этот порядок используется
для `configs`, TXT, stdout и файла hook; `--limit` сохраняет относительный порядок.
Адреса, которых нет в списке, выводятся после перечисленных в произвольном порядке.
