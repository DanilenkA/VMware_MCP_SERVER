# VMware_MCP_SERVER

Комплексный Model Context Protocol (MCP) сервер для управления VMware vSphere, предоставляющий AI-агентам полный доступ к операциям виртуальной инфраструктуры через безопасное Docker-окружение. **55+ инструментов в 12 категориях**, включая **полный набор read-only vSAN мониторинга** (10 инструментов) и **получение guest IP через pyVmomi** (2 инструмента).

## Основные улучшения

- ✅ Исправлены критические баги (requirements, REST endpoints, SSL)
- ✨ Добавлены инструменты для real-time метрик через pyVmomi PerformanceManager
- ✨ Добавлен **полный набор vSAN read-only мониторинга** (10 инструментов, Phase 0-5)
- ✨ Добавлены **guest IP tools** (`get_vm_ip`, `list_vm_ips`) — REST API vCenter не отдаёт guest IP, реализация через pyVmomi `vm.guest` (Phase 6)
- 🔒 CA-aware SSL для безопасных production-соединений
- 📚 Расширенная документация на русском языке
- 🎯 SKILL.md / EXAMPLE_SKILL.md — готовые к использованию гайды для AI-агентов

---

## Возможности

### Управление виртуальными машинами
- **Список ВМ** — получение всех виртуальных машин с состояниями питания
- **Детали ВМ** — подробная информация о конкретных ВМ
- **Операции питания** — запуск, остановка, перезагрузка ВМ
- **Мониторинг ресурсов** — использование CPU, RAM и сети
- **Информация о хранилище** — использование дисков и датасторов
- **Guest IP** — `get_vm_ip` (детально по одной ВМ) и `list_vm_ips` (сводка по всем ВМ) через pyVmomi `vm.guest`

### Продвинутые операции
- **Управление snapshot'ами** — создание, список и удаление снимков ВМ
- **Управление template'ами** — список и управление шаблонами ВМ
- **Массовые операции** — операции питания над множеством ВМ
- **Модификация ресурсов** — изменение выделения CPU и памяти
- **Управление сетью** — port groups и конфигурация сети

### Мониторинг и отчётность
- **Мониторинг производительности** — real-time использование ресурсов через pyVmomi PerformanceManager
- **Логирование событий** — события ВМ и системные логи
- **Управление алармами** — активные алармы и оповещения
- **Комплексные отчёты** — аналитика по всему окружению
- **Использование ресурсов** — метрики CPU, памяти, диска и сети

### Функции безопасности
- **Система подтверждения** — все деструктивные операции требуют явного подтверждения
- **Обработка ошибок** — понятные сообщения об ошибках и troubleshooting
- **Безопасная аутентификация** — управление credentials через переменные окружения с CA-aware SSL
- **Audit trail** — прозрачное логирование всех операций

---

## Новые инструменты

### ✨ Real-time метрики через pyVmomi

#### `get_vm_metrics`
Получение детальных метрик производительности виртуальной машины:
- CPU: usage/ready
- Memory: active/consumed
- Disk: read/write/latency
- Network: received/transmitted

**Важно:** Для guest-level метрик требуется VMware Tools. Выключенные ВМ не возвращают realtime данные.

#### `get_host_metrics`
Получение детальных метрик производительности ESXi хоста:
- Те же метрики, что для ВМ
- Детализация по ядрам CPU
- Агрегированная статистика

### 🔧 Исправленные инструменты

- **`get_alarms`** — теперь работает через pyVmomi AlarmManager (был 404)
- **`get_vm_events`** — теперь работает через pyVmomi EventManager (был 404)
- **`get_host_details`** — исправлен workaround для vCenter 8.0.3+

### 🛰️ vSAN monitoring (10 read-only инструментов, Phase 0-4)

Все инструменты vSAN — **строго read-only (Tier 1)**. Деструктивные vSAN-операции (add/remove/claim disk, evacuate, witness add/remove) **НЕ реализованы** и не входят в scope. Бэкенд: pyVmomi SOAP на `/vsanHealth` endpoint (`vim.version.version11`); исключение — `get_vsan_storage_policies` через REST.

- **`list_vsan_clusters`** — все vSAN-enabled кластеры с числом хостов, MoRef, vSAN UUID
- **`get_vsan_cluster_health`** — overall 🟢/🟡/🔴 + per-host через `VsanVcClusterHealthSystem`
- **`get_vsan_capacity_info`** — total/free/used TB через `VsanSpaceReportSystem`
- **`get_vsan_disk_groups`** — cache SSD + capacity tier per host через `QueryDiskMappings` (per-host итерация обязательна)
- **`get_vsan_performance_metrics`** — IOPS, throughput, latency, congestion для кластера через `VsanPerformanceManager`
- **`get_vsan_health_checks`** — overall + 9 health-групп + per-host node state (master/backup/agent)
- **`get_vsan_objects`** — все vSAN объекты с разбивкой по типам (vdisk/namespace/vmswap/...) и SPBM-профилям
- **`get_vsan_storage_policies`** — все SPBM-политики vCenter (REST), фильтр по vSAN-related
- **`get_vsan_capabilities`** — 122+ фичи vCenter с иконками по категориям
- **`get_vsan_witness_info`** — witness host(s) для stretched кластеров; graceful "not stretched" для обычных

**Известные ограничения (vCenter 8.0.3):**
- vSAN-specific REST endpoints (`vcenter/vsan/*`) → 404 (не существуют), используется pyVmomi
- SPBM detail endpoints (`/pbm/profile`, `/vcenter/storage/policies/{id}`) → 404, политики показывают только name/id/description
- Compliance endpoints (`/vcenter/storage/policies/compliance*`) → 404 (доступны с 8.0 U3+)
- Witness IP/connectivity недоступны через API (только через vSphere Client UI)
- Idle vSAN кластеры возвращают пустые perf-samples — это валидный production-state, не ошибка

### 🌐 Guest IP retrieval (Phase 6)

REST API vCenter **не отдаёт guest IP** в принципе — он живёт только в `vim.vm.GuestInfo`, доступном через pyVmomi SOAP. Реализовано 2 read-only инструмента (Tier 1):

- **`get_vm_ip(vm_name, hostname=None)`** — детальный guest IP одной ВМ через pyVmomi `vm.guest`: primary IP + guest hostname + VMware Tools version + per-NIC (network, MAC, connected, IPv4/IPv6 + prefixLength). Graceful fallback если ВМ не найдена / не powered on / Tools не запущены.
- **`list_vm_ips(hostname=None)`** — одноразовая сводка через один PropertyCollector-запрос: имя + power state + guest IP для каждой powered-on ВМ с работающим Tools (templates пропускаются). Удобно для network inventory и "find VM by IP".

**Требования:** ВМ должна быть **powered on** и **VMware Tools должна быть запущена** (данные живут в `vm.guest`, без Tools = нет guest info). Live-протестировано на cluster12: `FF-UPTIME-3 → 10.20.34.159`.

Подробности в `SKILL.md` → секция "Virtual Machines — listing & details".

### ⚠️ Интерпретация метрик памяти

При работе с `get_vm_metrics`:
- **`mem.active`** — реально используемая память процессами гостевой ОС (ключевая метрика!)
- **`mem.consumed`** — зарезервировано ESXi гипервизором (включает overhead, кэши, balloon driver)
- **Не путайте:** `consumed` ≠ используется гостем. Если `active = 53 MB` при `consumed = 4 GB`, то гость использует только 53 MB.

---

## Установка

### Требования
- Docker и Docker Compose
- VMware vCenter Server 8.0+ с доступом к REST API
- Действительные credentials vCenter

### Быстрый старт

1. **Клонируйте репозиторий**
```bash
git clone https://github.com/yourusername/VMW-vsphere-mcp-server.git
cd VMW-vsphere-mcp-server
```

2. **Настройте окружение**
```bash
cp env.example .env
# Отредактируйте .env своими credentials vCenter
```

3. **Разверните через Docker**
```bash
docker compose up -d
```

---

## Конфигурация

### Переменные окружения

Создайте `.env` файл со следующими переменными:

```env
# Подключение к vCenter
VCENTER_HOST=vcenter.example.com
VCENTER_USER=username@vsphere.local
VCENTER_PASSWORD=your_password_here
INSECURE=False

# Опционально: CA сертификат для проверки SSL
REQUESTS_CA_BUNDLE=/path/to/ca-bundle.crt
# или
VCENTER_CA_BUNDLE=/path/to/vcenter-ca.crt

# Конфигурация сервера
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

### Интеграция с MCP клиентом

Пример конфигурации для MCP клиентов:

```json
{
  "mcpServers": {
    "vsphere-mcp-server": {
      "name": "vSphere MCP Server",
      "type": "streamable",
      "url": "http://vsphere-mcp-server:8000/mcp",
      "auth_token": null,
      "enabled": true
    }
  }
}
```

---

## Использование SKILL.md

В репозитории включён файл `SKILL.md` — комплексный гайд для использования всех 55+ инструментов MCP с AI-агентами.

### Что включено в SKILL.md

- **Полный список инструментов** — все 55+ инструментов по 12 категориям (включая vSAN monitoring + guest IP)
- **Паттерны использования** — правильные способы вызова инструментов
- **Примеры команд** — ready-to-use примеры для типичных задач
- **Система безопасности** — какие операции требуют подтверждения
- **Интерпретация метрик** — как правильно читать performance данные
- **Workflows** — end-to-end сценарии (клонирование ВМ, snapshot'ы, мониторинг, vSAN audit)

### Использование с AI-агентами

SKILL.md специально отформатирован для загрузки в контекст AI-агентов:

```python
# Пример: загрузка скилла в Claude Code
# Скилл автоматически доступен через skills директорию
```

AI-агент с загруженным SKILL.md:
- ✅ Знает все доступные инструменты
- ✅ Понимает правильные паттерны вызова
- ✅ Может выполнять комплексные workflows
- ✅ Соблюдает safety guardrails (подтверждения для деструктивных операций)

---

## Доступные инструменты

Полный список см. в `SKILL.md`. Основные категории:

### Управление ВМ
- `list_vms`, `get_vm_details`, `get_vm_metrics`
- `power_on_vm`, `power_off_vm`, `restart_vm`
- `clone_vm`, `delete_vm`, `modify_vm_resources`

### Управление инфраструктурой
- `list_hosts`, `get_host_details`, `get_host_metrics`
- `list_datastores`, `list_networks`, `list_datacenters`

### Мониторинг и производительность
- `get_vm_performance_info`, `get_host_performance_info`
- `get_vm_disk_usage`, `get_datastore_usage`
- `get_vms_with_high_resource_usage`

### Управление snapshot'ами
- `list_vm_snapshots`, `create_vm_snapshot`, `delete_vm_snapshot`

### Продвинутый мониторинг
- `get_vm_events`, `get_alarms`, `get_port_groups`

### Отчётность и аналитика
- `generate_vm_report`, `get_resource_utilization_summary`

### 🛰️ vSAN monitoring (read-only)
- `list_vsan_clusters` — список vSAN-кластеров
- `get_vsan_cluster_health`, `get_vsan_capacity_info`, `get_vsan_disk_groups`
- `get_vsan_performance_metrics`, `get_vsan_health_checks`
- `get_vsan_objects`, `get_vsan_storage_policies`, `get_vsan_capabilities`
- `get_vsan_witness_info` — для stretched кластеров

**⚠️ Деструктивные операции требуют явного подтверждения через `confirm=True`**
**⚠️ Все vSAN-инструменты — read-only (Tier 1), деструктивные vSAN-операции не реализованы**

---

## Технические детали

### Зависимости
- **Python:** 3.12+
- **pyvmomi:** 9.1.0.0 (VMware vSphere Python SDK)
- **mcp:** 1.14.1 (Model Context Protocol)
- **requests:** 2.32.5
- **FastMCP** для реализации MCP сервера

### Протестировано на
- vCenter Server 8.0.3 (builds 24022515, 24322831)
- ESXi 8.0.x хосты
- Python 3.12

### Архитектура
- **REST API** (`vsphere_client.py`) — для inventory и mutating операций
- **SOAP/pyVmomi** (`pyvmomi_client.py`) — для алармов, событий, метрик, vSAN (`/vsanHealth` endpoint), guest IP (`vm.guest`) и продвинутых операций
- **FastMCP** (`server.py`) — реализация MCP протокола с 55+ инструментами (12 категорий)

---

## Примеры использования

### Базовые операции с ВМ
```bash
# Список всех ВМ
"Покажи все виртуальные машины"

# Детали ВМ и метрики
"Получи детали для ВМ WebServer01"
"Покажи использование CPU и памяти для ВМ WebServer01"

# Операции питания
"Включи ВМ DatabaseServer"
"Перезагрузи ВМ: WebServer01, WebServer02"
```

### 🌐 Guest IP (поиск ВМ по IP / inventory)
```bash
# Получить IP одной ВМ (детально: hostname, Tools version, per-NIC)
"Какой IP у ВМ FF-UPTIME-3?"
"Покажи детальный guest IP для WebServer01"

# Сводка IP по всем ВМ
"Покажи IP всех ВМ"
"Найди ВМ с IP 10.20.34.159"
```

### Мониторинг производительности
```bash
# Real-time метрики
"Получи метрики производительности для ВМ WebServer01"
"Покажи метрики хоста host-21"

# Агрегированные метрики
"Покажи использование CPU и памяти для всех ВМ"
"Какие ВМ имеют высокое использование ресурсов?"

# Мониторинг хранилища
"Покажи использование датасторов"
"Какие ВМ имеют использование диска более 90%?"
```

### Мониторинг и отчётность
```bash
# События и алармы
"Покажи последние события для ВМ DatabaseServer"
"Получи активные алармы в окружении"
"Покажи алармы только для виртуальных машин"

# Комплексные отчёты
"Сгенерируй полный отчёт по vSphere окружению"
"Покажи сводку использования ресурсов"
```

### 🛰️ vSAN мониторинг (read-only)
```bash
# Inventory vSAN кластеров
"Покажи все vSAN кластеры"
"Какие vSAN кластеры в окружении?"

# Health и capacity
"Получи общий статус здоровья vSAN кластера New Cluster 122"
"Сколько свободного места в vSAN кластере New Cluster 122?"

# Производительность и объекты
"Покажи disk groups для vSAN кластера New Cluster 122"
"Сколько vSAN объектов в кластере New Cluster 122?"
"Покажи vSAN-related storage policies"

# Stretched cluster / witness
"Есть ли witness host для vSAN кластера New Cluster 122?"
```

---

## Функции безопасности

### Система подтверждения
Все деструктивные операции требуют явного подтверждения:

```python
# Первый вызов - показывает предупреждение
delete_vm(vm_id="TestServer", confirm=False)
# Возвращает: ⚠️ ДЕСТРУКТИВНАЯ ОПЕРАЦИЯ: Удаление ВМ TestServer...

# Второй вызов - выполняет операцию
delete_vm(vm_id="TestServer", confirm=True)
# Возвращает: ⚠️ ВМ TestServer успешно удалена
```

### Аутентификация через переменные окружения
- Credentials хранятся в переменных окружения
- Нет захардкоженных паролей
- Безопасный Docker deployment
- Поддержка SSL/TLS с проверкой CA сертификата

---

## Контрибьютор

- **DanilenkA** — автор всех улучшений и исправлений

---

## Лицензия

Apache 2.0 License

---

## Поддержка

По вопросам и проблемам открывайте issue в репозитории.
