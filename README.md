---
type: software
status: active
---
<div align="right">

**УТВЕРДИЛ**

Подколзин А.Е.

«_____» ________________ 2026 г.

Подпись ___________________

</div>

---

# ПРОГРАММНАЯ СПЕЦИФИКАЦИЯ
### программного обеспечения шлюза
# ДРОНПОРТ

> _Система управления OrangePi 5 Max ↔ STM32F401CUU6 ↔ БПЛА_

| **Параметр** | **Значение**            |
| ------------ | ----------------------- |
| Документ     | ДРОНПОРТ-СПО-001        |
| Версия       | 0.3 (актуализирована)   |
| Статус       | В разработке            |
| Дата         | 20 марта 2026 г.        |
| Разработчик  | Минеев Михаил Андреевич |

---

## Аннотация

Настоящий документ является программной спецификацией программного обеспечения автономной посадочной, зарядной и управляющей станции — дронпорта. Документ описывает программный шлюз, реализованный на одноплатном микрокомпьютере OrangePi 5 Max под управлением Ubuntu 24.04 LTS, написанный на языке Python 3.12 с применением асинхронной библиотеки asyncio.

Документ охватывает: назначение системы и концепцию обработки команд, полный аппаратный состав с описанием каждого исполнительного узла, архитектуру программного обеспечения и статус реализации каждого модуля, протоколы обмена данными (UDP с сервером, UART с микроконтроллером STM32, USART с БПЛА, USB-датчики), точную карту концевых датчиков, логику всех сценариев работы, обработку ошибок и процедуры развёртывания.

> _Назначение документа: используется как системный контекст-промпт для языковой модели Claude AI при разработке системы, а также как техническая документация для разработчиков. Данный документ — единственный авторитетный источник истины о системе._

---

## Содержание

- [1. Общие сведения о системе](#1-общие-сведения-о-системе)
  - [1.1. Назначение](#11-назначение)
  - [1.2. Аппаратный состав дронпорта](#12-аппаратный-состав-дронпорта)
  - [1.3. Концевые датчики — полная карта](#13-концевые-датчики--полная-карта)
  - [1.4. Зарядка БПЛА](#14-зарядка-бпла)
  - [1.5. Концепция обработки команд](#15-концепция-обработки-команд)
- [2. Архитектура программного обеспечения](#2-архитектура-программного-обеспечения)
  - [2.1. Структура файловой системы](#21-структура-файловой-системы)
  - [2.2. Статус реализации модулей](#22-статус-реализации-модулей)
- [3. Конфигурационные файлы](#3-конфигурационные-файлы)
  - [3.1. config/network.yaml](#31-confignetworkyaml--актуальная-версия)
  - [3.2. config/hardware.yaml](#32-confighardwareyaml--эталонная-структура)
- [4. Описание программных модулей](#4-описание-программных-модулей)
- [5. Протокол обмена с STM32 (UART)](#5-протокол-обмена-с-stm32-uart)
- [6. Протокол обмена с сервером (UDP)](#6-протокол-обмена-с-сервером-udp)
- [7. Протокол связи с БПЛА (radio_link, USART)](#7-протокол-связи-с-бпла-radio_link-usart)
- [8. Обработка ошибок](#8-обработка-ошибок)
- [9. Сценарии работы системы](#9-сценарии-работы-системы)
- [10. Файл scenarios.json — эталон](#10-файл-scenariosjson--эталон)
- [11. Развёртывание и эксплуатация](#11-развёртывание-и-эксплуатация)
- [12. Справочные таблицы](#12-справочные-таблицы)

---
# 1. Общие сведения о системе

## 1.1. Назначение

Дронпорт — автономная наземная станция для хранения, автоматической зарядки и управляемого выпуска/приёма беспилотного летательного аппарата. Один дронпорт обслуживает строго один БПЛА.

Программный шлюз (Gateway) — центральный вычислительный узел дронпорта. Он принимает команды от удалённого центрального сервера по UDP/Ethernet, оркестрирует все исполнительные механизмы через микроконтроллер STM32, взаимодействует с БПЛА через радиоканал, собирает телеметрию с USB-датчиков и отправляет отчёты серверу.

## 1.2. Аппаратный состав дронпорта

Ниже приведён исчерпывающий перечень всех аппаратных узлов с точным указанием количества, драйвера и программного интерфейса.

| **Узел**                                      | **Кол-во** | **Драйвер / Управление**                                                                                                                             | **GPIO / Интерфейс STM32** | **CMD STM32**     |
| --------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ----------------- |
| Актуаторы крыши (открытие в бок)              | 2          | ESC Hobbywing; управляются синхронно одной командой — одна PWM-линия STM32 на оба ESC                                                                | 1 линия TIM PWM            | 17 / 18           |
| Шаговые двигатели подъёма стола               | 2          | TB6600 №1 и TB6600 №2 — каждый шаговик стола управляется своим TB6600; оба TB6600 получают одинаковые STEP/DIR сигналы от STM32 и работают синхронно | STEP + DIR (TIM)           | 13 / 14           |
| Шаговый двигатель лапок (4 лапки от 1 мотора) | 1          | TB6600 №2; один шаговик двигает все 4 лапки через механическую передачу                                                                              | STEP + DIR (TIM)           | 15 / 16           |
| Нагревательные элементы воздуха               | 4          | Твердотельное реле (SSR) → транзистор на плате → GPIO STM32; все 5 включаются одновременно                                                           | 1 GPIO                     | 3 / 4             |
| Нагревательные пластины крыши                 | 6          | Твердотельное реле (SSR) → транзистор на плате → GPIO STM32; все 6 включаются одновременно                                                           | 1 GPIO                     | 5 / 6             |
| Вентиляторы проветривания (впуск + выпуск)    | 4          | Все 4 управляются одним GPIO STM32 — включаются/выключаются одновременно                                                                             | 1 GPIO                     | 11 / 12           |
| Заслонки вентиляторов (один мотор)            | 1          | L298N H-bridge → GPIO STM32 (два сигнала: открыть / закрыть)                                                                                         | 2 GPIO                     | 9 / 10            |
| Резервный аккумулятор 12В LiFePO4             | 2          | Делитель напряжения R1=10 кОм / R2=1 кОм (коэф. 1/11) → ADC STM32. Реальное U = ADC_value × 11                                                       | ADC вход                   | запрос напряжения |
| Светодиодная лента (подсветка площадки)       | 1          | Транзистор на плате → GPIO STM32                                                                                                                     | 1 GPIO                     | 7 / 8             |
| Вибромоторы (антиобледенение)                 | 2          | Транзистор на плате → GPIO STM32; все 3 включаются одновременно                                                                                      | 1 GPIO                     | 1 / 2             |
| USB-камера (трансляция на сервер)             | 1          | USB → OrangePi напрямую; постоянный видеопоток с момента запуска системы                                                                             | USB (OrangePi)             | —                 |
| GPS VK-162 G-Mouse (u-blox G6010)             | 1          | USB → /dev/ttyACM0; 9600 бод; NMEA 0183                                                                                                              | USB (OrangePi)             | —                 |
| Метеостанция (Arduino Nano)                    | 1          | 2×AS5600 (флюгер + анемометр) + DHT22; USB → /dev/ttyUSB1 (CH340); 115200 бод; 8N1                                                                  | USB (OrangePi)             | —                 |
| Микроконтроллер STM32F401CUU6                 | 1          | USART1 STM32 → UART3 OrangePi (/dev/ttyS3); 115200 бод; 3.3V TTL \| UART3                                                                            | UART0                      | —                 |
| Радиопередатчик БПЛА                          | 1          | /dev/ttyUSB0; 115200 бод; собственный бинарный протокол                                                                                              | USB→UART (OrangePi)        | —                 |

## 1.3. Концевые датчики — полная карта

В системе 7 концевых датчиков (физические кнопки-концевики). Все подключены к порту PB микроконтроллера STM32. Электрически и программно работают идентично датчикам Холла: при срабатывании дают логическую 1 на входе GPIO. Номер бита в байте ответа = номер датчика − 1.

| **№ датчика** | **Бит в байте** | **Пин STM32** | **Контролируемое состояние** | **Активен (=1) когда** |
|---|---|---|---|---|
| 1 | Бит 0 | PB0 | Крыша открыта | Актуаторы раздвинуты до конца — крыша полностью открыта |
| 2 | Бит 1 | PB1 | Крыша закрыта | Актуаторы сдвинуты — крыша полностью закрыта |
| 3 | Бит 2 | PB2 | Стол поднят | Шаговики стола довели платформу в верхнюю позицию |
| 4 | Бит 3 | PB3 | Стол опущен | Шаговики стола довели платформу в нижнюю позицию |
| 5 | Бит 4 | PB4 | Заслонка вентиляции 1 закрыта | Мотор L298N довёл заслонку №1 в закрытое положение |
| 6 | Бит 5 | PB5 | Заслонка вентиляции 2 закрыта | Мотор L298N довёл заслонку №2 в закрытое положение |
| 7 | Бит 6 | PB7 | Лапки дрона сжаты (дрон зафиксирован) | Шаговик лапок сомкнул все 4 лапки — БПЛА зафиксирован и заряжается |
| 8 | Бит 7 | PB8 | Резерв (не используется) | — |

> _Концевые датчики являются единственным средством верификации положения механизмов. Энкодеров в системе нет._

> _Лапки дрона: 4 сегментных зажима, охватывающих цилиндрический корпус БПЛА. Все 4 лапки механически связаны с одним шаговым двигателем через передачу. Концевик 7 фиксирует только сжатое положение (лапки разжаты = бит 6 = 0)._

## 1.4. Зарядка БПЛА

Зарядка дрона осуществляется через контактные площадки, расположенные непосредственно на лапках. При смыкании лапок (CMD 16) токопроводящие пластины лапок входят в контакт с соответствующими площадками на корпусе БПЛА, и зарядный ток начинает поступать автоматически. Таким образом, команда «закрыть лапки» одновременно фиксирует дрон и запускает зарядку.

## 1.5. Концепция обработки команд

Система работает как асинхронный событийно-управляемый шлюз в едином asyncio event loop (без threading). Поток обработки входящей команды:

1. Сервер отправляет UDP-датаграмму на порт 5001 OrangePi.
2. `UDPInitializer` (udp_server_init.py) принимает байты и вызывает зарегистрированный callback.
3. `UDPServerRX` (udp_server_rx.py) валидирует пакет: маркеры DLE+STX/ETX, поле ID=2001, NUM=droneport_id, контрольную сумму. При ошибке — NACK серверу.
4. `UDPServerRX` передаёт `DronePortPacket` зарегистрированному обработчику команды.
5. `CommandHandlers` (command_handlers.py) последовательно исполняет шаги из scenarios.json через движок `_run_scenario_steps()`: STM32-команды, ожидание по таймауту, верификация концевых датчиков, команды БПЛА.
6. `UDPServerTX` (udp_server_tx.py) формирует ответный пакет и отправляет серверу.
7. `ErrorHandler` (error_handler.py) агрегирует ошибки и отправляет ERROR-пакеты (CMD=48) серверу.
8. `Watchdog` (watchdog.py) — **не реализован** (заглушка). Планируется: heartbeat, мониторинг АКБ, антиобледенение, видеопоток.

---

# 2. Архитектура программного обеспечения

## 2.1. Структура файловой системы

```
drone_gateway/
├── config/
│   ├── network.yaml             # Сетевые параметры, debug-флаги
│   ├── hardware.yaml            # Порты, тайминги, пороговые значения
│   └── scenarios.json           # Шаги многошаговых сценариев
├── src/
│   ├── __init__.py
│   ├── main.py                  # Точка входа; инициализация; event loop
│   ├── core/
│   │   ├── __init__.py
│   │   ├── command_handlers.py  # ✅ Хендлеры команд + движок сценариев
│   │   └── command_router.py    # ❌ Заглушка (def CommandRouter(): return 0)
│   ├── interfaces/
│   │   ├── __init__.py
│   │   ├── udp_server_init.py   # ✅ UDP сокет (asyncio.DatagramProtocol)
│   │   ├── udp_server_rx.py     # ✅ Парсинг входящих UDP-пакетов
│   │   ├── udp_server_tx.py     # ✅ Формирование и отправка UDP-пакетов
│   │   ├── usart_drone_init.py  # ✅ USART инициализация (pyserial-asyncio)
│   │   ├── usart_drone_rx.py    # 🔶 Заготовка — парсер пакетов-заглушка
│   │   ├── usart_drone_tx.py    # 🔶 Заготовка — формат пакета не соответствует р.7
│   │   ├── uart_stm32_init.py   # ❌ Заглушка (def STM32Interface(): return 0)
│   │   ├── uart_stm32_rx.py     # ❌ Пустой файл
│   │   ├── uart_stm32_tx.py     # ❌ Пустой файл
│   │   ├── radio_link.py        # ❌ Заглушка (def RadioLink(): return 0)
│   │   └── usb_sensors.py       # ❌ Заглушка (def USBSensors(): return 0)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── logger.py            # ✅ RotatingFileHandler + StreamHandler
│   │   ├── error_handler.py     # ✅ Сборка ERROR-пакетов, буферизация
│   │   └── watchdog.py          # ❌ Заглушка (def Watchdog(): return 0)
│   └── utils/
│       ├── __init__.py
│       └── helpers.py           # ✅ calculate_checksum, bytes_to_hex
├── tests/
│   ├── udp_writer.py            # ✅ Эмулятор сервера (отправка команд)
│   └── udp_listener.py          # ✅ Сниффер UDP-пакетов (отладка)
├── logs/system.log              # Единый журнал событий и ошибок
├── requirements.txt             # (содержимое не заполнено — нет зависимостей)
└── systemd_service.service      # (содержимое не заполнено)
```

> **Важно: модуля `state_machine.py` не существует.** Его функциональность полностью реализована внутри `command_handlers.py` через метод `_run_scenario_steps()` и движок диспетчеризации шагов `_dispatch_step()`.

## 2.2. Статус реализации модулей

| **Модуль** | **Статус** | **Примечание** |
|---|---|---|
| src/interfaces/udp_server_init.py | ✅ Реализован | Полнофункциональный asyncio UDP-сокет; защита от повторного bind() |
| src/interfaces/udp_server_rx.py | ✅ Реализован | Парсинг пакетов, диспетчер хендлеров, ServerCommand enum |
| src/interfaces/udp_server_tx.py | ✅ Реализован | Сборка пакетов, ACK/NACK, DroneportCommand enum |
| src/interfaces/usart_drone_init.py | ✅ Реализован | USART инициализация, send_raw, rx_loop |
| src/interfaces/usart_drone_rx.py | 🔶 Заготовка | Буфер и диспетчер готовы; парсер пакетов — заглушка (возвращает GENERIC) |
| src/interfaces/usart_drone_tx.py | 🔶 Заготовка | Базовый build_packet готов; формат не соответствует протоколу radio_link из р.7 |
| src/interfaces/uart_stm32_init.py | ❌ Заглушка | `def STM32Interface(): return 0` — требует реализации протокола (Раздел 5) |
| src/interfaces/uart_stm32_rx.py | ❌ Пустой файл | Требует реализации приёма UART от STM32 |
| src/interfaces/uart_stm32_tx.py | ❌ Пустой файл | Требует реализации отправки UART на STM32 |
| src/interfaces/radio_link.py | ❌ Заглушка | `def RadioLink(): return 0` — требует реализации (Раздел 7) |
| src/interfaces/usb_sensors.py | ❌ Заглушка | `def USBSensors(): return 0` — GPS, камера (Раздел 4.9) |
| src/interfaces/uart_weather.py | ✅ Реализован | Интерфейс метеостанции Arduino Nano по USB (/dev/ttyUSB1) (Раздел 4.9.2) |
| src/core/command_handlers.py | ✅ Реализован | Все хендлеры зарегистрированы; движок сценариев (_run_scenario_steps) реализован; заглушки для железа через None-проверки |
| src/core/command_router.py | ❌ Заглушка | `def CommandRouter(): return 0` — не используется |
| src/services/logger.py | ✅ Реализован | RotatingFileHandler 5 МБ, 3 бэкапа; формат ISO-8601 |
| src/services/error_handler.py | ✅ Реализован | Полный маппинг 25 кодов ошибок; буферизация до 50 записей; flush_buffer |
| src/services/watchdog.py | ❌ Заглушка | `def Watchdog(): return 0` — периодические задачи не реализованы (Раздел 4.14) |
| src/utils/helpers.py | ✅ Реализован | calculate_checksum (XOR), bytes_to_hex |
| src/main.py | ✅ Реализован | Полная инициализация системы; заглушки для uart_stm32, radio_link, usb_sensors через None |

---

# 3. Конфигурационные файлы

## 3.1. config/network.yaml — актуальная версия

```yaml
server:
  ip: "127.0.0.1"           # Продакшн: реальный IP сервера
  port: 5000                 # UDP-порт сервера (куда дронпорт ОТПРАВЛЯЕТ)
  timeout: 5.0
  retry_count: 3

droneport:
  id: 1                      # NUM дронпорта (1..254)
  subsystem_id: 2001         # ID подсистемы (фиксировано протоколом)
  status_interval: 420       # Heartbeat STATUS_DRONEPORT — 7 минут

local:
  bind_ip: "0.0.0.0"
  bind_port: 5001            # Порт дронпорта (куда сервер ПРИСЫЛАЕТ команды)
  ethernet_interface: "eth0"

debug:
  log_raw_packets: true      # Логировать сырые байты hex
  echo_mode: true            # Заглушки без железа
  simulate_server: false

timings:
  udp_receive_timeout: 1.0
  command_execution_timeout: 30.0
  heartbeat_interval: 60.0
```

> ⚠️ **Продакшн:** установить `server.ip` = реальный IP; `debug.log_raw_packets: false`; `debug.echo_mode: false`.

## 3.2. config/hardware.yaml — эталонная структура

```yaml
uart_stm32: 
  port: "/dev/ttyS3"         # UART3 OrangePi ↔ USART1 STM32
  baudrate: 115200
  inter_byte_timeout_ms: 100
  max_retries: 3

usart_drone:
  port: "/dev/ttyUSB0"       # Радиопередатчик БПЛА
  baudrate: 115200

gps:
  port: "/dev/ttyACM0"       # VK-162 G-Mouse (NMEA 0183)
  baudrate: 9600

weather_station:
  port: "/dev/ttyUSB1"        # Arduino Nano метеостанция (CH340 USB)
  baudrate: 115200

action_timeouts:            # Секунд ожидания после команды STM32 (со стороны OrangePi)
  open_roof:   15           # CMD 17 — PWM на ESC Hobbywing; STM32 таймаут 15000 мс
  close_roof:  29           # CMD 18 — PWM реверс; STM32 таймаут 29000 мс
  raise_table: 30           # CMD 13 — 55000 шагов + до 15×50 добивка; ~20-25 сек реально
  lower_table: 30           # CMD 14 — аналогично
  open_clamps:  8           # CMD 15 — TB6600 №2 (1 шаговик, 4 лапки); 8000 шагов
  close_clamps: 8           # CMD 16 — 8000 шагов + проверка концевика PB7
  open_vent:   8            # CMD 9  — L298N (заслонки)
  close_vent:  8            # CMD 10
  default:     0            # Моментальные команды (LED, вибро, нагрев, вентиляторы)

radio_timeouts:             # Секунд ожидания пакетов от БПЛА
  diag_result:      20      # CMD 45 — ответ на PRE_FLIGHT
  demo_result:      20      # CMD 43 — завершение DEMO_MODE
  boarding_request: 20      # CMD 44 — запрос посадки
  drone_flight:     20      # CMD 44 — завершение перелёта
  return_receive:   20      # CMD 44 — посадка после RETURN

sensor_timeouts:            # Секунд ожидания датчиков
  gps_fix:     20           # Ожидание GPS-фикса при PRE_FLIGHT
  weather:     5            # Ответ метеостанции Arduino (UART, быстрый)

thresholds:
  battery_min_voltage:      11.0   # В. Ниже → BATTERY_LOW
  battery_critical_voltage:  9.5   # В. Ниже → BATTERY_CRITICAL
  vibro_temp_threshold:     -10.0  # °C. Ниже → включать вибромоторы
  vibro_interval_sec:       1800   # 30 мин между включениями
  vibro_duration_sec:         10   # Длительность одного включения
```

> _АКБ 12В LiFePO4. Делитель напряжения: R1=10 кОм (к VCC), R2=1 кОм (к GND). Коэффициент 1/11. Формула: `U_real = ADC_voltage × 11`. Диапазон LiFePO4: заряжен ~13.6В, разряжен ~10В._

---

# 4. Описание программных модулей

## 4.1. src/main.py — точка входа

Реализован. Последовательность запуска:

1. Инициализация logger (DEBUG в разработке, INFO в продакшне).
2. Загрузка `config/network.yaml` и `config/hardware.yaml`.
3. Создание `UDPInitializer` + `UDPServerRX` + `UDPServerTX`.
4. Создание `ErrorHandler` с callback → `udp_tx.send_packet`.
5. Создание `CommandHandlers` с заглушками `uart_stm32=None`, `radio_link=None`, `usb_sensors=None`.
6. Регистрация хендлеров: `handlers.register_all(rx_module=udp_rx)`.
7. Запуск воркера очереди: `handlers.start_worker()`.
8. Ожидание через `stop_event.wait()` (KeyboardInterrupt → корректное завершение).
9. При завершении: `STATUS_DRONEPORT(ready=False)` → `error_handler.shutdown()` → `udp_init.stop()`.

> _Следующий этап: реализовать `uart_stm32`, `radio_link`, `usb_sensors` и передать в конструктор `CommandHandlers(...)` вместо `None`. Фоновые задачи watchdog добавить через `asyncio.gather()` или как отдельные `asyncio.Task`._

## 4.2. src/interfaces/udp_server_init.py — UDP-транспорт

Реализован. Оборачивает `asyncio.DatagramProtocol`.

| **Метод** | **Описание** |
|---|---|
| `start() → bool` | Создаёт сокет, привязывает к bind_ip:bind_port |
| `stop()` | Закрывает сокет |
| `send_raw(data, addr?) → bool` | Отправляет байты. Адрес по умолчанию — server_ip:server_port из конфига |
| `set_receive_callback(cb)` | Регистрирует callback(data: bytes, addr: tuple) |

## 4.3. src/interfaces/udp_server_rx.py — приём UDP

Реализован. Структура входящего пакета (реализация в `_parse_packet`):

| **Байты** | **Поле** | **Тип** | **Значение / проверка** |
|---|---|---|---|
| 0–1 | DLE+STX | 0x10, 0x02 | Стартовый маркер |
| 2–3 | ID | uint16 **Little Endian** | Всегда 2001. Проверяется по subsystem_id из конфига |
| 4 | NUM | uint8 | Номер дронпорта. Проверяется по droneport_num |
| 5 | LEN | uint8 | Длина DATA (0..71) |
| 6–7 | CMD | uint16 **Little Endian** | Код команды от сервера |
| 8..8+LEN-1 | DATA | bytes | Полезная нагрузка |
| 8+LEN | CHECKSUM | uint8 | sum(core_bytes) % 256 |
| 8+LEN+1..+2 | DLE+ETX | 0x10, 0x03 | Стоповый маркер |

> **Поле ID занимает 2 байта (uint16 LE) — зафиксировано в коде. Согласовано с сервером: 2 байта с обеих сторон. Минимальный размер пакета: 11 байт.**

## 4.4. src/interfaces/udp_server_tx.py — отправка UDP

Реализован. Сборка пакета: `DLE+STX + [ID(2б LE) | NUM(1б) | LEN(1б) | CMD(2б LE) | DATA] + CHECKSUM + DLE+ETX`.

| **Метод** | **Описание** |
|---|---|
| `send_packet(cmd, data?, addr?) → bool` | Основной метод. Собирает и отправляет пакет |
| `send_ack(original_cmd, success, error_code?) → bool` | ACK (0xF1) или NACK (0xF2). DATA=[CMD_original, error_code] |
| `send_status_droneport(ready) → bool` | Shortcut: CMD=35, DATA=[1] или DATA=[0] |
| `send_external_param(temp_in, temp_out, wind_spd, wind_dir, reserved=0) → bool` | CMD=33, struct.pack('<hhBhB', ...). temp_in из STM32 DHT22, остальное из метеостанции Arduino |
| `send_error_packet(errors: list[bytes]) → bool` | CMD=48, data=b''.join(errors) |

## 4.5. src/interfaces/usart_drone_init.py — USART к БПЛА

Реализован. Инициализирует USART через pyserial-asyncio (primary) или pyserial sync (fallback). `DroneRadioType=CUSTOM` (протокол собственный). Методы: `start()`, `stop()`, `send_raw(data)`, `read_raw(size)`, `start_receive_loop()`.

## 4.6. src/interfaces/usart_drone_rx.py — приём от БПЛА

Заготовка. Архитектура (буфер → парсер → хендлеры) готова. Требует реализации парсера по протоколу из Раздела 7: поиск `FRAME_START` (0xAA, 0x55) в байтовом потоке, сборка пакета, верификация CHECKSUM.

## 4.7. src/interfaces/usart_drone_tx.py — отправка БПЛА

Заготовка. Текущий формат `_build_packet`: `[CMD(1б) | LEN(1б) | DATA | CRC]`. Требует переработки под протокол radio_link из Раздела 7: `FRAME_START(2б) + CMD(2б) + LEN(1б) + DATA + CRC(1б) + FRAME_END(1б)`.

## 4.8. src/interfaces/uart_stm32_init.py / uart_stm32_rx.py / uart_stm32_tx.py — драйвер STM32

Заглушки. `uart_stm32_init.py` содержит `def STM32Interface(): return 0`. `uart_stm32_rx.py` и `uart_stm32_tx.py` — пустые файлы. Требуется полная реализация бинарного протокола (Раздел 5). Физика: Физика: /dev/ttyS3 ↔ USART1 STM32, 115200 бод, 8N1, 3.3V TTL. 
Пины: Orange Pi 5 Max pin 31 (GPIO3_B5, TX) → STM32 RX, pin 33 (GPIO3_B6, RX) → STM32 TX, pin 30 (GND) → STM32 GND. 
Overlay: rk3588-uart3-m1.dtbo прописан в /boot/extlinux/extlinux.conf.

> _В `main.py` и `command_handlers.py` STM32-интерфейс передаётся как `uart_stm32=None`. Все вызовы методов STM32 внутри `command_handlers.py` защищены условием `if self.uart_stm32 is None: return stub_value`. При подключении реального объекта STM32 — передать в конструктор `CommandHandlers(uart_stm32=...)` в `main.py`._

Требуемый публичный интерфейс:

| **Метод** | **Сигнатура** | **Описание** |
|---|---|---|
| send_action | `async send_action(code: int) → bool` | CMD действия (биты[2:1]=10). code: 1–21 |
| read_hall_sensors | `async read_hall_sensors() → int` | Запрос концевых датчиков (system_part=1). Возвращает uint8: бит N = концевик N+1 |
| read_voltage | `async read_voltage() → float` | Запрос напряжения АКБ (system_part=2). Возвращает В. Расчёт: raw/10 × 11 = U_real |
| read_dht22 | `async read_dht22() → tuple[float,float]` | Запрос DHT22 (system_part=3). Возвращает (темп °C, влажность %) |

## 4.9. src/interfaces/usb_sensors.py — USB-датчики

### 4.9.1. GPS VK-162 G-Mouse

`/dev/ttyACM0` @ 9600 бод. Чип u-blox G6010. Протокол NMEA 0183. Предложения: `$GPGGA` (координаты, высота, качество фикса), `$GPRMC` (координаты, скорость, курс). Метод `get_coordinates() → dict{latitude, longitude, altitude, fix_quality, satellites, timestamp}`.

### 4.9.2. Метеостанция (Arduino Nano) — src/interfaces/uart_weather.py

Автономная метеостанция на Arduino Nano. Подключение: USB-кабель Arduino Nano → OrangePi (`/dev/ttyUSB1`, чип CH340), 115200 бод, 8N1. Питание Arduino от USB OrangePi.

**Датчики на Arduino:**
- 2× AS5600 (I²C, разные адреса или мультиплексор): один на флюгере (направление ветра), один на чашечном анемометре (скорость ветра)
- 1× DHT22: температура и влажность наружного воздуха

**Протокол запрос-ответ:**

Запрос от OrangePi: один байт `0x01`.

Ответ от Arduino: 8 байт, little-endian, без заголовков и CRC:

| **Смещение** | **Размер** | **Тип**  | **Поле**    | **Единицы**                              |
|---|---|---|---|---|
| 0 | 2 | uint16 | wind_dir    | Градусы (0–359)                          |
| 2 | 2 | uint16 | wind_spd    | м/с × 10 (например 53 = 5.3 м/с). При отправке серверу обрезается до uint8 (максимум 25.5 м/с) |
| 4 | 2 | uint16 | temperature | °C × 10 + 1000 смещение (например 1253 = +25.3°C, 950 = −5.0°C). OrangePi конвертирует: int16 = (raw − 1000) → struct '<h' |
| 6 | 2 | uint16 | humidity    | % × 10 (например 654 = 65.4%). Не отправляется серверу, используется для логирования |

**Метод:** `read_weather() → dict{temperature, humidity, wind_speed, wind_dir}` или `None` при таймауте.

**Логика OrangePi при формировании CMD=33:**
1. `uart_stm32.read_dht22()` → `temp_in` (int16, температура внутри корпуса)
2. `uart_weather.read_weather()` → `temp_out` (конверсия из uint16), `wind_spd` (uint16 → uint8), `wind_dir` (uint16 → int16)
3. `struct.pack('<hhBhB', temp_in, temp_out, wind_spd & 0xFF, wind_dir, 0)` → CMD=33 серверу

### 4.9.3. USB-камера

Непрерывный видеопоток с момента запуска системы (не по команде). Реализуется как `asyncio.Task` через subprocess (ffmpeg или gstreamer). Метод `start_stream(server_ip, server_port)`. Работает параллельно и не блокирует обработку команд.

## 4.10. src/core/command_handlers.py — хендлеры команд и движок сценариев

Реализован. Архитектура:

- Каждый хендлер немедленно отвечает ACK серверу, затем кладёт задачу в `asyncio.Queue` через `_enqueue()`.
- Единственный `_worker()` выполняет задачи строго по одной — никакого параллелизма.
- Шаги сценария разворачиваются через `_run_scenario_steps()`, который читает `scenarios.json` и вызывает `_dispatch_step()`.
- `STOP` и `RETURN` — приоритетные: сбрасывают очередь через `_clear_queue()` немедленно.
- Всё железо (uart_stm32, radio_link, usb_sensors) передаётся как зависимость; при `None` используются встроенные заглушки с правдоподобными данными.

| **Хендлер**                | **CMD**                | **Статус** | **Примечание**                                                     |
| -------------------------- | ---------------------- | ---------- | ------------------------------------------------------------------ |
| handle_open_droneport      | 1 OPEN_DRONPORT        | ✅          | Сценарий OPEN_DRONEPORT через движок                               |
| handle_close_droneport     | 2 CLOSE_DRONPORT       | ✅          | Сценарий CLOSE_DRONEPORT                                           |
| handle_diagnostic          | 3 DIAGNOSTIC           | ✅          | Сценарий DIAGNOSTIC                                                |
| handle_condition_dron      | 4 CONDITION_DRON       | ✅          | Немедленно: Холл + АКБ → CMD=32                                    |
| handle_external_param      | 5 EXTERNAL_PARAM       | ✅          | Немедленно: STM32 DHT22 (temp_in) + Arduino метеостанция (temp_out, wind) → CMD=33 |
| handle_request_coordinate  | 6 REQUEST_COORDINATE   | ✅          | Немедленно: GPS → CMD=34                                           |
| handle_status_shutters     | 7 STATUS_SHUTTERS      | ✅          | Немедленно: Холл → CMD=30                                          |
| handle_status              | 8 STATUS               | ✅          | Немедленно: STATUS_DRONEPORT(35) + ACK                             |
| handle_combat_mode         | 20 COMBAT_MODE         | ✅          | Сценарий COMBAT_MODE                                               |
| handle_target_interception | 21 TARGET_INTERCEPTION | ✅          | Сценарий TARGET_INTERCEPTION                                       |
| handle_demo_mode           | 22 DEMO_MODE           | ✅          | Сценарий DEMO_MODE                                                 |
| handle_sector_search       | 23 SECTOR_SEARCH       | ✅          | Сценарий SECTOR_SEARCH                                             |
| handle_diagnostic_flight   | 24 DIAGNOSTIC_FLIGHT   | ✅          | Сценарий DIAGNOSTIC_FLIGHT                                         |
| handle_drone_flight        | 25 DRONE_FLIGHT        | ✅          | Проверяет num_src; сценарий DRONE_FLIGHT                           |
| handle_stop                | 26 STOP                | ✅          | Приоритет: ACK → _clear_queue() → RADIO(STOP)                      |
| handle_return              | 27 RETURN              | ✅          | Приоритет: ACK → _clear_queue() → RADIO(RETURN) → ожидание посадки |
| handle_pre_flight          | 28 PRE_FLIGHT          | ✅          | Сценарий PRE_FLIGHT                                                |
| handle_coordinate_ned      | 29 COORDINATE_NED      | ✅          | Прямая ретрансляция radio_link без ACK и очереди                   |

Добавление нового хендлера:
1. `async def handle_X(self, packet) → _enqueue(self._run_X, packet)`
2. `async def _run_X(self, packet) → _run_scenario_steps("X", packet)`
3. Зарегистрировать в `register_all()`

## 4.11. Движок сценариев (в command_handlers.py) — вместо state_machine.py
Движок сценариев — методы `_run_scenario_steps()` и `_dispatch_step()` класса `CommandHandlers`.

**Жизненный цикл команды:**

```
handle_X(packet)              → ACK серверу + _enqueue(_run_X, packet)
_worker()                     → берёт из asyncio.Queue по одной задаче
_run_X(packet)                → вызывает _run_scenario_steps("X", packet)
_run_scenario_steps()         → итерирует шаги scenarios.json
_dispatch_step(step, store)   → вызывает execute_* функцию по step["type"]
```

**Роль очереди как замена состояний конечного автомата:**

| **Проектируемое состояние** | **Реализация в коде** |
|---|---|
| IDLE | `_queue.empty() == True` |
| RUNNING | `_queue.qsize() > 0` или выполняется задача в `_worker` |
| WAITING_VERIFY | `await asyncio.sleep(timeout)` внутри `execute_stm32_action()` |
| ERROR | `except Exception` → `error_handler.report_error()` → возврат из корутины |
| CANCELLED | `asyncio.CancelledError` при `_clear_queue()` + `task.cancel()` |

**Хранилище результатов шагов (`store`):**

Каждый сценарий получает изолированный словарь `store: dict`. Шаг с `"store_as": "ключ"` сохраняет результат. Шаг `"data_source": "stored:ключ"` читает из него. При вложенных сценариях (`sub_scenario`) `store` передаётся по ссылке — вложенный сценарий видит данные родителя.

**Типы шагов и функции-исполнители:**

| **step["type"]** | **Функция** | **Местоположение** |
|---|---|---|
| `stm32_action` | `execute_stm32_action()` | module-level функция в command_handlers.py |
| `stm32_request` | `execute_stm32_request()` | module-level функция |
| `radio_command` | `_step_radio_command()` | метод CommandHandlers |
| `wait_radio` | `execute_wait_radio()` | module-level функция |
| `usb_sensor` | `execute_usb_sensor()` | module-level функция |
| `send_server` | `_step_send_server()` | метод CommandHandlers |
| `sub_scenario` | `_step_sub_scenario()` | метод CommandHandlers (рекурсивно) |

## 4.12. src/services/error_handler.py — обработчик ошибок

Реализован. Вызов: `await error_handler.report_error(code='SHUTTER_TIMEOUT', message='...', severity=Severity.ERROR)`. Коды ошибок — в Разделе 8. `ErrorEntry.to_bytes()` → 4 байта: `[error_class | subsystem | code | flags]`. Буферизация до 50 записей при недоступности сервера, `flush_buffer()` при восстановлении.

`CommandHandlers._extract_error_code(message)` — вспомогательный метод: извлекает строковый код из исключения вида `"[КОД] текст"` для передачи в `error_handler.report_error()`. Если формат не соответствует — возвращает `"MECHANICS"` по умолчанию.

## 4.13. src/services/logger.py — логирование

Реализован. `setup_logger(name, level, log_file_path)`: StreamHandler (stdout) + RotatingFileHandler (5 МБ, 3 бэкапа). Формат: `YYYY-MM-DD HH:MM:SS | LEVEL | module | message`.

## 4.14. src/services/watchdog.py — фоновые задачи

Заглушка. Проектируемые `asyncio.Task`:

| **Задача** | **Периодичность** | **Логика** |
|---|---|---|
| STATUS heartbeat | Каждые 420 сек | udp_tx.send_status_droneport(ready=True) |
| UART watchdog | Каждые 30 сек | uart_stm32.read_voltage(). 3 неудачи → DRONE_NO_RESPONSE (WARNING) |
| Мониторинг АКБ | Каждые 5 мин | read_voltage(). < 11.0В → BATTERY_LOW; < 9.5В → BATTERY_CRITICAL |
| Антиобледенение | T < −10°C И раз в 30 мин | STM32(CMD 1) на 10 сек → STM32(CMD 2). T берётся из последнего запроса: STM32 DHT22 (внутр.) или Arduino метеостанция (наруж.) |
| Видеопоток камеры | Постоянно с запуска | usb_sensors.start_stream(server_ip, server_port) → ffmpeg/gstreamer subprocess |

---

# 5. Настройка STM32 
STM32 является промежуточным слоем между ORANGE Pi и аппаратными модулями (например ESC для актуаторов, датчиками, управляемыми механическими устройствами). Основное назначение - реализовывать работу всех физических модулей, находящихся в дронпорте после прочтения пакета данных, полученных от OrangePi
## 5.1 Аппаратная конфигурация
## 5.2 Тактирование
Тактирование:
- HSE: 4 МГц (внешний кварц)
- PLL: PLLM=2, PLLN=42, PLLP=2 → SYSCLK = 42 МГц
- AHB (HCLK): 84 МГц (делитель 1)
- APB1: 42 МГц (делитель 1) → TIM2, TIM3, TIM4 = 84 МГц...
- APB2: 84 МГц (делитель 1) → USART1, ADC1
## 5.3 Модули STM32
### 5.3.1 Карта GPIO
| Пин          | Режим             | Назначение                     |
| ------------ | ----------------- | ------------------------------ |
| PA0          | Output            | Вибромоторы                    |
| PA1          | Analog (ADC1_IN1) | Делитель АКБ 12В               |
| PA2          | Output            | Нагрев воздуха (SSR)           |
| PA3          | Output            | Светодиодная лента             |
| PA4          | Output            | Вентилятор проветривания       |
| PA5          | Output            | L298N направление 1 (заслонки) |
| PA6          | AF2 (TIM3_CH1)    | PWM → ESC крыши                |
| PA7          | Output OD         | DHT22 data                     |
| PA9          | AF7 (USART1_TX)   | UART → OrangePi                |
| PA10         | AF7 (USART1_RX)   | UART ← OrangePi                |
| PA11         | Output            | L298N направление 2 (заслонки) |
| PB0–PB5, PB7 | Input             | Концевые датчики 1–7           |
| PB9          | Output            | TB6600 стол — ENA              |
| PB10         | Output            | TB6600 стол — DIR              |
| PB11         | Output            | TB6600 стол — STEP             |
| PB13         | Output            | TB6600 лапки — ENA             |
| PB14         | Output            | TB6600 лапки — DIR             |
| PB15         | Output            | TB6600 лапки — STEP            |
| PC13         | Output            | Нагрев крыши (SSR)             |
### 5.3.2 UART
USART1 (STM32 ↔ OrangePi):
- Периферия: APB2, f_CLK = 84 МГц
- BRR = 84000000 / 115200 = 729
- Формат: 8N1 (8 бит, без чётности, 1 стоп-бит)
- Oversampling: 16 (OVER8 = 0)
- RX: прерывание RXNEIE, приоритет NVIC = 1
- TX: блокирующий (поллинг TXE + TC)
- Межбайтовый таймаут: 100 мс (INTER_BYTE_TIMEOUT_US = 100000 мкс, TIM2)
### 5.3.3 Таймеры
TIM2 — счётчик микросекунд (getMicros):
- APB1, f = 42 МГц
- PSC = 83 → 84 МГц / 84 = 1 МГц = 1 тик/мкс
- ARR = 0xFFFFFFFF (переполнение раз в ~71 мин)
- Используется для межбайтового таймаута UART и замера длительности бит DHT22

TIM3 — PWM для ESC крыши (PA6, TIM3_CH1, AF2):
- APB1, f = 42 МГц
- PSC = 41 → 1 МГц (1 тик = 1 мкс)
- ARR = 19999 → период 20 мс (50 Гц)
- CCR1: диапазон 1000–2000 мкс (ESC_MIN / ESC_MAX)
- Открыть крышу: 2000 мкс / Закрыть: 1000 мкс
### 5.3.4 PWM
Шим, используемый для управления ESC. Управляется под таймером TIM3 (настройка таймера выше)
```c
#ifndef PWM_H
#define PWM_H

#include <stdint.h>

// Инициализация PWM на PA6 (TIM3_CH1)
void PWM_Init(void);

// Установка ширины импульса в микросекундах (для ESC)
// Диапазон: 1000 - 2000 мкс
void PWM_SetPulseWidth(uint16_t microseconds);

// Установка процента заполнения (0-100%)
void PWM_SetDutyPercent(uint8_t percent);

// Включение/выключение PWM сигнала
void PWM_Enable(void);
void PWM_Disable(void);

#endif
```
```c
#include "pwm.h"
#include "stm32f401xc.h"

// ─── Константы для ESC ───
#define ESC_MIN_PULSE  1000  // Мин. импульс (мкс) - мотор стоп
#define ESC_MAX_PULSE  2000  // Макс. импульс (мкс) - полный газ
#define ESC_NEUTRAL    1500  // Нейтраль (мкс)
#define PWM_PERIOD_US  20000 // Период 20 мс (50 Гц)

// ─── Настройки таймера (при 42 МГц) ───
// Prescaler = 41 → 42 МГц / 42 = 1 МГц (1 тик = 1 мкс)
// ARR = 19999 → 20000 тиков = 20000 мкс = 20 мс (50 Гц)
#define TIM_PRESCALER  41
#define TIM_ARR        19999

void PWM_Init(void) {
    // ─── 1. Тактирование ───
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;   // GPIOA
    RCC->APB1ENR |= RCC_APB1ENR_TIM3EN;    // TIM3
    
    // ─── 2. Настройка PA6 (TIM3_CH1, AF2) ───
    GPIOA->MODER &= ~GPIO_MODER_MODER6;    // Сброс режима
    GPIOA->MODER |= GPIO_MODER_MODER6_1;   // Alternate Function
    GPIOA->OSPEEDR |= GPIO_OSPEEDER_OSPEEDR6; // High speed
    GPIOA->PUPDR &= ~GPIO_PUPDR_PUPDR6;    // Без подтяжки
    GPIOA->AFR[0] &= ~(0xF << 24);    // Очистить старые биты 
		GPIOA->AFR[0] |=  (2 << 24);      // Установить AF2 = TIM3
    
    // ─── 3. Настройка TIM3 ───
    TIM3->CR1 &= ~TIM_CR1_CEN;             // Остановить таймер
    
    TIM3->PSC = TIM_PRESCALER;             // Предделитель (1 МГц)
    TIM3->ARR = TIM_ARR;                   // Период (20 мс)
    
    // Настройка канала 1 (PA6) в режим PWM
    TIM3->CCMR1 &= ~TIM_CCMR1_CC1S;        // CC1 = выход
    TIM3->CCMR1 |= TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2; // PWM mode 1
    TIM3->CCMR1 |= TIM_CCMR1_OC1PE;        // Предзагрузка включена
    
    TIM3->CCER |= TIM_CCER_CC1E;           // Включить выход на пин
    TIM3->CCER &= ~TIM_CCER_CC1P;          // Полярность: высокий активный
    
    TIM3->EGR |= TIM_EGR_UG;               // Обновить регистры
    TIM3->CR1 |= TIM_CR1_CEN;              // Запустить таймер
    
    // По умолчанию: импульс 1500 мкс (нейтраль)
    PWM_SetPulseWidth(ESC_NEUTRAL);
}

void PWM_SetPulseWidth(uint16_t microseconds) {
    // Ограничение диапазона
    if (microseconds < ESC_MIN_PULSE) microseconds = ESC_MIN_PULSE;
    if (microseconds > ESC_MAX_PULSE) microseconds = ESC_MAX_PULSE;
    
    // При 1 МГц: 1 мкс = 1 тик таймера
    TIM3->CCR1 = microseconds;
}

void PWM_SetDutyPercent(uint8_t percent) {
    if (percent > 100) percent = 100;
    
    // Конвертация процента в микросекунды (1000-2000 мкс)
    uint16_t pulse = ESC_MIN_PULSE + ((uint32_t)percent * (ESC_MAX_PULSE - ESC_MIN_PULSE)) / 100;
    PWM_SetPulseWidth(pulse);
}

void PWM_Enable(void) {
    TIM3->CR1 |= TIM_CR1_CEN;
}

void PWM_Disable(void) {
    TIM3->CR1 &= ~TIM_CR1_CEN;
}
```
### 5.3.5 ADC
Аналоговый пин-вход для показаний напряжения аккумулятора резервной батареи (ДРОНПОРТА, не дрона)
файл adc.h:
```c
#ifndef ADC_H
#define ADC_H

#include <stdint.h>

// Инициализация ADC1 на PA1
void ADC_Init(void);

// Чтение сырого значения ADC (0-4095)
uint16_t ADC_ReadRaw(void);

#endif
```
Файл adc.c
```c
#include "adc.h"
#include "stm32f401xc.h"

// ─── Инициализация ADC1 на PA1 (делитель напряжения АКБ) ───
void ADC_Init(void) {
    // ─── 1. Тактирование ───
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;   // GPIOA
    RCC->APB2ENR |= RCC_APB2ENR_ADC1EN;     // ADC1 (на APB2)

    // ─── 2. PA1 → аналоговый режим (MODER = 0b11) ───
    GPIOA->MODER |= GPIO_MODER_MODER1;

    // ─── 3. Настройка ADC1 ───
    ADC1->CR2 &= ~ADC_CR2_ADON;             // Выключить ADC для настройки

    // Разрешение: 12 бит (RES = 00)
    ADC1->CR1 &= ~ADC_CR1_RES;

    // Время выборки канала 1: 84 цикла (SMP1 = 0b100)
    // Делитель 10к/1к = ~910 Ом импеданс → нужно >= 84 циклов
    ADC1->SMPR2 &= ~ADC_SMPR2_SMP1;
    ADC1->SMPR2 |= ADC_SMPR2_SMP1_2;        // 100 = 84 цикла

    // Канал: Channel 1 (PA1 = ADC1_IN1)
    ADC1->SQR3 &= ~ADC_SQR3_SQ1;
    ADC1->SQR3 |= (1 << 0);                 // SQ1 = канал 1

    // Количество преобразований: 1
    ADC1->SQR1 &= ~ADC_SQR1_L;              // L = 0 → 1 преобразование

    // ─── 4. Включение ADC ───
    // STM32F401 не имеет автокалибровки ADC (это фича F1/F3/L4)
    ADC1->CR2 |= ADC_CR2_ADON;
    for (volatile int i = 0; i < 1000; i++); // Ждём стабилизации (~2 мкс)
}

// ─── Чтение сырого значения (0-4095) ───
uint16_t ADC_ReadRaw(void) {
    // Запуск преобразования
    ADC1->CR2 |= ADC_CR2_SWSTART;
    
    // Ждём завершения (флаг EOC)
    while (!(ADC1->SR & ADC_SR_EOC));
    
    // Читаем результат (12 бит)
    return (uint16_t)(ADC1->DR & 0x0FFF);
}
```
### 5.3.6 DHT22
Драйвер датчика температуры и влажности DHT22 (AM2302). Однопроводной протокол на PA7, тайминги замеряются аппаратным таймером TIM2 через `getMicros()` (из rcc.h). Это обеспечивает устойчивость к прерываниям (USART1 IRQ и др.), т.к. TIM2 тикает аппаратно, независимо от CPU.

**Принцип работы протокола DHT22:**
1. МК тянет линию LOW на 2 мс (стартовый сигнал)
2. МК отпускает линию на 30 мкс
3. Датчик отвечает: LOW 80 мкс → HIGH 80 мкс
4. Датчик передаёт 40 бит: каждый бит = LOW ~50 мкс + HIGH (26-28 мкс = '0', 70 мкс = '1')
5. Определение бита: замер длительности HIGH-фазы через getMicros(), порог BIT_THRESHOLD_US = 20 тиков

**Требования:** внешний pull-up резистор 4.7–10 кОм на линии данных PA7. Минимальный интервал между чтениями: 2 секунды.

Файл dht22.h
```c
#ifndef DHT22_H
#define DHT22_H

#include <stdint.h>
#include <stdbool.h>
#include "stm32f401xc.h"

// Инициализация (вызвать 1 раз в начале программы)
void DHT22_Init(void);

// Чтение данных с датчика
// Возвращает: true = успех, false = ошибка
// data[5] всегда заполняется:
//   - при успехе: данные датчика
//   - при ошибке: все 5 байт = 0
bool DHT22_Read(uint8_t data[5]);

// Конвертация сырых данных в удобные величины
float DHT22_GetHumidity(uint8_t data[5]);
float DHT22_GetTemperature(uint8_t data[5]);

#endif
```
Файл dht22.c
```c
#include "dht22.h"
#include "rcc.h"

// ─── Константы ───
#define TIMEOUT_US       200       // Таймаут ожидания любой фазы (мкс)
#define BIT_THRESHOLD_US 20        // Порог: бит '0' ≈ 11 тиков, бит '1' ≈ 28 тиков

// ─── Вспомогательные функции для работы с PA7 ───

static inline void PA7_Output_Low(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->MODER |=  GPIO_MODER_MODER7_0;
    GPIOA->ODR &= ~(1 << 7);
}

static inline void PA7_Output_High(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->MODER |=  GPIO_MODER_MODER7_0;
    GPIOA->ODR   |=  (1 << 7);
}

static inline void PA7_Input_PullUp(void) {
    GPIOA->MODER &= ~GPIO_MODER_MODER7;
    GPIOA->PUPDR &= ~GPIO_PUPDR_PUPDR7;
    GPIOA->PUPDR |=  GPIO_PUPDR_PUPDR7_0;
}

static inline uint8_t PA7_Read(void) {
    return (GPIOA->IDR & (1 << 7)) ? 1 : 0;
}

// ─── Ожидание состояния пина с таймаутом (через TIM2) ───
// Ждёт пока пин == level, возвращает false если таймаут
static inline bool WaitForLevel(uint8_t level, uint32_t timeout_us) {
    uint32_t start = getMicros();
    while (PA7_Read() == level) {
        if ((getMicros() - start) >= timeout_us) return false;
    }
    return true;
}

// ─── Вспомогательная функция: очистка буфера нулями ───
static inline void ClearData(uint8_t data[5]) {
    data[0] = 0;
    data[1] = 0;
    data[2] = 0;
    data[3] = 0;
    data[4] = 0;
}

// ─── Инициализация ───
void DHT22_Init(void) {
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    PA7_Input_PullUp();
}

// ─── Чтение данных с DHT22 ───
bool DHT22_Read(uint8_t data[5]) {
    uint8_t byteIndex = 0, bitIndex = 0;
    uint8_t i;
    uint32_t start;

    // ─── СРАЗУ очищаем буфер (на случай ошибки) ───
    ClearData(data);

    // ─── 1. Стартовый сигнал от МК ───
    PA7_Output_Low();
    start = getMicros();
    while ((getMicros() - start) < 2000);  // 2 мс LOW

    PA7_Output_High();
    start = getMicros();
    while ((getMicros() - start) < 30);    // 30 мкс HIGH

    PA7_Input_PullUp();

    // ─── 2. Ждём ответа датчика ───
    if (!WaitForLevel(1, TIMEOUT_US)) { ClearData(data); return false; }
    if (!WaitForLevel(0, TIMEOUT_US)) { ClearData(data); return false; }
    if (!WaitForLevel(1, TIMEOUT_US)) { ClearData(data); return false; }

    // ─── 3. Чтение 40 бит данных ───
    for (i = 0; i < 40; i++) {
        // Ждём окончания LOW-фазы (~50 мкс)
        if (!WaitForLevel(0, TIMEOUT_US)) { ClearData(data); return false; }

        // Засекаем начало HIGH-фазы
        start = getMicros();

        // Ждём окончания HIGH-фазы
        if (!WaitForLevel(1, TIMEOUT_US)) { ClearData(data); return false; }

        // Определяем бит по длительности HIGH
        if ((getMicros() - start) > BIT_THRESHOLD_US) {
            data[byteIndex] |= (1 << (7 - bitIndex));
        }

        bitIndex++;
        if (bitIndex == 8) {
            bitIndex = 0;
            byteIndex++;
        }
    }

    // ─── 4. Проверка CRC ───
    uint8_t crc = (data[0] + data[1] + data[2] + data[3]) & 0xFF;
    if (data[4] != crc) {
        ClearData(data);
        return false;
    }

    return true;
}

// ─── Конвертация в удобные величины ───
float DHT22_GetHumidity(uint8_t data[5]) {
    if (data[0] == 0 && data[1] == 0) return 0.0f;
    return ((float)data[0] * 256.0f + (float)data[1]) / 10.0f;
}

float DHT22_GetTemperature(uint8_t data[5]) {
    if (data[2] == 0 && data[3] == 0) return 0.0f;
    float temp = ((float)(data[2] & 0x7F) * 256.0f + (float)data[3]) / 10.0f;
    if (data[2] & 0x80) {
        temp = -temp;
    }
    return temp;
}
```
## 5.4 Климат контроль
Климат-контроль (isClimatic, CMD 19/20):
- Источник данных: DHT22 на PA7
- Нагрев воздуха вкл: temp <= 10°C (PA2)
- Нагрев воздуха выкл: temp >= 20°C
- Заслонки открыть: temp <= 15°C (Airing_control)
- Заслонки закрыть: temp >= 35°C
- Принудительное проветривание: humidity > 90% (открыть на 25 сек, закрыть)
# 5. Протокол обмена с STM32 (UART)

## 5.1. Физический уровень

| **Параметр** | **Значение**                                  |
| ------------------ | --------------------------------------------- |
| Порт OrangePi | /dev/ttyS3 (UART0, физические контакты платы) |
| Порт STM32 | USART1                                        |
| Скорость | 115200 бод                                    |
| Формат | 8 бит данных, нет чётности, 1 стоп-бит (8N1)  |
| Уровни | 3.3V TTL (совместимо с обоими устройствами)   |
| Управление потоком | Отсутствует (без RTS/CTS)                     |
| Топология | Точка–точка (1:1)                             |
| Порядок байт | Little Endian для многобайтовых полей         |

## 5.2. Структура пакета

| **Поле**   | **Байт(ы)** | **Значение**                                                   |
| ---------- | ----------- | -------------------------------------------------------------- |
| BYTE_START | 1           | `0xBF` — маркер начала. Не может встречаться в DATA            |
| TYPE       | 1           | Битовая маска: источник \| тип команды \| подсистема (см. 5.3) |
| LEN        | 1           | Длина DATA (0..255)                                            |
| DATA       | 0..255      | Полезная нагрузка. Формат зависит от TYPE (см. 5.4–5.5)        |
| CHECKSUM   | 1           | sum(TYPE + LEN + DATA[0..N-1]) % 256                           |
| BYTE_END   | 1           | `0xFF` — маркер конца. Не может встречаться в DATA             |
|            |             |                                                                |

## 5.3. Байт TYPE

| **Биты** | **Поле** | **Кодировка** |
|---|---|---|
| Бит 0 | Source | 0 = от STM32 (ответ/ошибка); 1 = от OrangePi (команда/запрос) |
| Биты 1–2 | Command Type | 00 = Запрос статуса; 01 = Ответ; 10 = Команда действия; 11 = Ошибка |
| Биты 3–5 | System Part | 000=Software; 001=Концевые датчики; 010=Напряжение АКБ; 011=DHT22; 100–111=Резерв |
| Биты 6–7 | Reserved | Всегда 0 |

## 5.4. Команды действия (Command Type = 10) и их аппаратный маппинг

| **Код** | **Команда** | **Аппаратный узел** | **Механизм управления** |
|---|---|---|---|
| 1 | Старт вибромоторов (×3) | 3 вибромотора | GPIO STM32 → транзистор на плате → все 3 одновременно |
| 2 | Стоп вибромоторов | — | GPIO STM32 → транзистор → выкл. |
| 3 | Старт нагрева воздуха | 5 нагревательных элементов | GPIO STM32 → транзистор → SSR → все 5 одновременно (220В) |
| 4 | Стоп нагрева воздуха | — | GPIO STM32 → транзистор → SSR → выкл. |
| 5 | Старт нагрева крыши | 6 нагревательных пластин | GPIO STM32 → транзистор → SSR → все 6 одновременно (220В) |
| 6 | Стоп нагрева крыши | — | GPIO STM32 → транзистор → SSR → выкл. |
| 7 | Включить LED-ленту | LED-лента подсветки | GPIO STM32 → транзистор → лента |
| 8 | Выключить LED-ленту | — | GPIO STM32 → транзистор → выкл. |
| 9 | Открыть заслонки | Мотор заслонок вентиляции | GPIO STM32 → L298N H-bridge → мотор (направление «открыть») |
| 10 | Закрыть заслонки | Мотор заслонок вентиляции | GPIO STM32 → L298N H-bridge → мотор (направление «закрыть») |
| 11 | Включить вентиляторы | 4 вентилятора | Один GPIO STM32 → все 4 вентилятора одновременно |
| 12 | Выключить вентиляторы | — | GPIO STM32 → все 4 выкл. |
| 13 | Поднять стол | 2 шаговика стола | STEP/DIR STM32 → TB6600 №1 и TB6600 №2 синхронно → шаговик стола 1 и шаговик стола 2 |
| 14 | Опустить стол | 2 шаговика стола | STEP/DIR STM32 → TB6600 №1 и TB6600 №2 реверс синхронно |
| 15 | Открыть лапки | 1 шаговик лапок → 4 лапки | STEP/DIR STM32 → TB6600 №2 → разжать лапки (отключает зарядку) |
| 16 | Закрыть лапки | 1 шаговик лапок → 4 лапки | STEP/DIR STM32 → TB6600 №2 → сжать лапки (включает зарядку) |
| 17 | Открыть крышу | 2 актуатора + 2 ESC Hobbywing | TIM PWM STM32 → оба ESC синхронно → актуаторы раздвигаются |
| 18 | Закрыть крышу | 2 актуатора + 2 ESC Hobbywing | TIM PWM STM32 → оба ESC синхронно → актуаторы сдвигаются |
| 19 | Включить климат-контроль | Нагрев воздуха + заслонки + вентиляторы | GPIO STM32 (внутренний флаг). STM32 устанавливает climate_flag=True и самостоятельно управляет нагревом по температуре |
| 20 | Выключить климат-контроль | — | GPIO STM32 (внутренний флаг). STM32 сбрасывает climate_flag=False, останавливает автономный термоконтроль |
| 21 | Поднять стол на порцию | 2 шаговика стола | STEP/DIR STM32 → TB6600 №1 и TB6600 №2 синхронно → фиксированная порция шагов (TABLE_NUDGE_STEPS=50) без проверки концевика. Всегда ACK. Используется для частичного подъёма стола перед открытием крыши |

> _CMD 21 (поднять стол на порцию): Делает ровно TABLE_NUDGE_STEPS (50) шагов вверх и сразу возвращает ACK. Не пров��ряет концевик — используется в сценарии OPEN_DRONEPORT перед открытием крыши, чтобы стол приподнялся и не мешал створкам. После открытия крыши стол поднимается до конца через CMD 13._

> _CMD 19/20 (климат-контроль): STM32 управляет температурой автономно. CMD 19 устанавливает внутренний флаг климат-контроля в True — STM32 сам начинает следить за температурой внутри дронпорта и включает/выключает нагрев по собственной логике. Любая прямая команда управления нагревом (CMD 3, 4, 5, 6) от OrangePi сбрасывает флаг климат-контроля в False. CMD 20 явно выключает климат-контроль._

## 5.5. Форматы DATA для ответов STM32

### 5.5.1. Ответ концевых датчиков (system_part=001, Command Type=01)

LEN=1. DATA[0] = uint8. Бит N (нумерация с 0) соответствует концевику N+1:

| **Бит** | **Концевик** | **STM32 пин** | **Состояние при бит=1** |
|---|---|---|---|
| 0 | Концевик 1 | PB0 | Крыша открыта полностью |
| 1 | Концевик 2 | PB1 | Крыша закрыта полностью |
| 2 | Концевик 3 | PB2 | Стол поднят |
| 3 | Концевик 4 | PB3 | Стол опущен |
| 4 | Концевик 5 | PB4 | Заслонка вентиляции 1 закрыта |
| 5 | Концевик 6 | PB5 | Заслонка вентиляции 2 закрыта |
| 6 | Концевик 7 | PB7 | Лапки сжаты (дрон зафиксирован, зарядка активна) |
| 7 | Концевик 8 | PB8 | Резерв (всегда 0) |

### 5.5.2. Ответ напряжения АКБ (system_part=010, Command Type=01)

LEN=2. DATA = uint16 Little Endian. Это сырое значение от STM32 (уже пересчитанное с делителя). Формула восстановления: `U_real (В) = raw_value / 10.0`. Делитель 1/11 учтён на стороне STM32 в прошивке.

Пример: raw=120 → U_real = 12.0В. Диапазон LiFePO4 12В: 12.8В (заряжен) ... 10.0В (разряжен).

### 5.5.3. Ответ DHT22 (system_part=011, Command Type=01)

LEN=5. Сырой 5-байтовый пакет датчика: байты 0–1 = влажность×10, байты 2–3 = температура×10, байт 4 = CRC датчика. OrangePi декодирует самостоятельно.

### 5.5.4. Сообщения об ошибке STM32 (Command Type=11)

| **System Part** | **DATA[0]** | **Значение**                                                                          |
| --------------- | ----------- | ------------------------------------------------------------------------------------- |
| 001 (Hall)      | N           | Концевик N (1–7) не сработал в ожидаемое время                                        |
| 010 (Voltage)   | 1 / 2       | 1=напряжение ниже порога; 2=выше порога                                               |
| 011 (DHT22)     | 0–4         | 0=слишком жарко; 1=холодно; 2=влажно; 3=сухо; 4=ошибка CRC датчика                    |
| 000 (Software)  | 0–2         | 0=ошибка CRC пакета; 1=переполнение буфера; 2=переполнение очереди, 3=превышена длина |

## 5.6. Тайминги и верификация

### Верификация на стороне OrangePi (шлюз)

1. Отправить STM32 `send_action(code)`.
2. Ожидать `hardware.yaml[action_timeouts][key]` секунд.
3. Если verify_hall: вызвать `read_hall_sensors()`, проверить нужный бит концевика.
4. Если бит в ожидаемом состоянии — шаг выполнен успешно.
5. Если нет — повторить шаги 1–3. Максимум 3 попытки суммарно.
6. После 3 неудач: `report_error('SHUTTER_TIMEOUT' / 'TABLE_TIMEOUT')` → ERROR серверу.

### Верификация на стороне STM32 (прошивка)

STM32 самостоятельно проверяет концевики после выполнения механической команды. Алгоритм зависит от типа привода:

**Шаговики стола (CMD 13 / 14):**
1. Основной прогон: `makeSteps(dir, STEP_MOTOR_TABLE_UPPER/LOWER_TIMEOUT)` — 55000 шагов.
2. Проверка концевика (PB2 для подъёма, PB3 для опускания).
3. Если не сработал — добивка: цикл до `STEP_MOTOR_HALL_RETRIES` (15) попыток по `TABLE_NUDGE_STEPS` (50) шагов с проверкой концевика после каждой порции.
4. Если за 15 попыток концевик не сработал → пакет ошибки (error_code=3 для подъёма, 4 для опускания), ACK не отправляется.
5. Если концевик сработал (на основном прогоне или при добивке) → ACK.

**PWM крыши (CMD 17 / 18):**
1. Установить PWM: `PWM_MAX` (открытие) или `PWM_MIN` (закрытие).
2. Запустить таймер `getMicros()`. Цикл `while` до таймаута: `ROOF_SHUTTERS_OPEN_TIMEOUT` (15000 мс) или `ROOF_SHUTTERS_CLOSE_TIMEOUT` (29000 мс). Каждую итерацию проверяется концевик (PB0 для открытия, PB1 для закрытия).
3. При срабатывании концевика — досрочный выход из цикла.
4. Стоп ESC: `PWM_CENTER`.
5. Если концевик не сработал за время таймаута → пакет ошибки, ACK не отправляется.
6. Если сработал → ACK.

**Шаговик лапок (CMD 15 / 16) и заслонки (CMD 9 / 10):**
Выполняются на фиксированное количество шагов без промежуточной проверки концевиков. CMD 16 (закрытие лапок) проверяет концевик PB7 после полного прогона.

Межбайтовый таймаут: 100 мс. Если пауза между байтами одного пакета > 100 мс → буфер сбрасывается, ожидается новый `BYTE_START` (0xBF).

> ⚠️ **Значения `0xBF` и `0xFF` зарезервированы как маркеры. Поле DATA не должно содержать эти байты. При коллизии — модифицировать данные на уровне приложения.**

---

# 6. Протокол обмена с сервером (UDP)
Протокол описан документом [[Протокол_дронпортa_финальный (2).pdf]]
## 6.1. Кадрирование

Кадр: `<DLE><STX>(0x10, 0x02) + [ID(2б) | NUM(1б) | LEN(1б) | CMD(2б) | DATA] + CHECKSUM(1б) + <DLE><ETX>(0x10, 0x03)`.

CHECKSUM = sum(байты между маркерами) % 256. CMD и ID — **Little Endian** uint16 (реализация: `struct.pack('<HBBH', id, num, len, cmd)`).

> **Поле ID занимает 2 байта (uint16 LE) — зафиксировано в коде `udp_server_rx.py` и `udp_server_tx.py`. Согласовано с сервером: 2 байта с обеих сторон.**

## 6.2. Команды Сервер → Дронпорт

| **CMD** | **Имя** | **DATA** | **Исполнитель** |
|---|---|---|---|
| 1 | OPEN_DRONPORT | — | `CommandHandlers` → сценарий OPEN_DRONEPORT |
| 2 | CLOSE_DRONPORT | — | `CommandHandlers` → сценарий CLOSE_DRONEPORT |
| 3 | DIAGNOSTIC | — | `CommandHandlers` → сценарий DIAGNOSTIC |
| 4 | CONDITION_DRON | — | `uart_stm32` → Холл + напряжение → CMD=32 |
| 5 | EXTERNAL_PARAM | — | `uart_stm32` (DHT22 внутр.) + `uart_weather` (Arduino метеостанция) → CMD=33 |
| 6 | REQUEST_COORDINATE | — | `usb_sensors` → GPS → CMD=34 |
| 7 | STATUS_SHUTTERS | — | `uart_stm32` → read_hall_sensors() → CMD=30 |
| 8 | STATUS | — | `CommandHandlers` → STATUS_DRONEPORT(35) + ACK |
| 20 | COMBAT_MODE | 13 б (X,Y,Z int32 ×10⁷ + резерв) | `CommandHandlers` → сценарий COMBAT_MODE |
| 21 | TARGET_INTERCEPTION | 13 б | `CommandHandlers` → сценарий TARGET_INTERCEPTION |
| 22 | DEMO_MODE | 13 б | `CommandHandlers` → сценарий DEMO_MODE |
| 23 | SECTOR_SEARCH | 16 б (X,Y,Z + azimuth_center uint16 + azimuth_width uint8) | `CommandHandlers` → сценарий SECTOR_SEARCH |
| 24 | DIAGNOSTIC_FLIGHT | — | `CommandHandlers` → сценарий DIAGNOSTIC_FLIGHT |
| 25 | DRONE_FLIGHT | 12 б (num_src + num_dst + X,Y int32) | `CommandHandlers` → сценарий DRONE_FLIGHT |
| 26 | STOP | — | ПРИОРИТЕТ: `_clear_queue()` + `radio_link.send_command(STOP)` |
| 27 | RETURN | — | ПРИОРИТЕТ: `_clear_queue()` + `radio_link.send_command(RETURN)` + OPEN если нужно |
| 28 | PRE_FLIGHT | — | `CommandHandlers` → сценарий PRE_FLIGHT |
| 29 | COORDINATE_NED | 13 б (X,Y,Z NED int32 ×10⁷) | прямая ретрансляция `radio_link` @ 200 Гц (без очереди) |

## 6.3. Ответы Дронпорт → Сервер

| **CMD** | **Имя** | **DATA** | **Когда** |
|---|---|---|---|
| 30 | RESULT_STATUS_SHUTTERS | 2 б: [статус, резерв]. Статус: 0=закрыто, 1=открыто, −1=ошибка | После OPEN/CLOSE/STATUS_SHUTTERS |
| 31 | RESULT_DIAGNOSTIC | 3 б: занята_ячейка \| заряжается \| резерв | После DIAGNOSTIC |
| 32 | RESULT_CONDITION_DRONE | 7 б: ячейка \| напряжение(2б) \| ёмкость(2б) \| статус_зарядки \| резерв | После CONDITION_DRON |
| 33 | RESULT_EXTERNAL_PARAM | 8 б: struct '<hhBhB' (temp_in \| temp_out \| wind_spd \| wind_dir \| резерв) | После EXTERNAL_PARAM |
| 34 | RESPONSE_COORDINATE_DRONEPORT | 12 б: X,Y,Z int32 (lat/lon ×10⁷, alt ×100) | После REQUEST_COORDINATE |
| 35 | STATUS_DRONEPORT | 1 б: 1=готов, 0=не готов, −1=ошибка | После STATUS + каждые 420 с (watchdog) |
| 40 | TELEMETRY_FAST | 78 б (ретрансляция с БПЛА) | @ 200 Гц в лётных сценариях |
| 41 | TELEMETRY_SLOW | 29 б (ретрансляция с БПЛА) | @ 10 Гц в лётных сценариях |
| 42 | SOS | 14 б (GPS флаг + координаты) | Событие: SOS от БПЛА |
| 43 | DEMO_RESULT | 14 б (флаги + координаты поражения) | Событие: завершение DEMO_MODE |
| 44 | BOARDING_REQUEST | 0 б | Событие: запрос посадки от БПЛА |
| 45 | DIAG_RESULT | 6 б (флаги + коды ошибок) | Событие: PRE_FLIGHT / DIAGNOSTIC_FLIGHT |
| 46 | TARGET | 1 б: 0=нет, 1=обнаружена, 2=ошибка | Событие: обнаружение цели |
| 47 | RETURN_DRONE | 4 б: напряжение(2б) + причина + резерв | Событие: БПЛА возвращается |
| 48 | ERROR | 4×N б (массив структур ошибок) | Любая ошибка системы |

## 6.4. Приоритеты и конкурирующие команды

| **Ситуация** | **Поведение** |
|---|---|
| Новая команда пришла пока сценарий выполняется | Команда ставится в очередь (`asyncio.Queue`). Исполняется после завершения текущей. Исключение: STOP и RETURN |
| STOP (CMD 26) | Немедленно: ACK → `_clear_queue()` → `radio_link.send_command(STOP)`. Механизмы дронпорта остаются в текущем положении |
| RETURN (CMD 27) | Немедленно: ACK → `_clear_queue()` → `radio_link.send_command(RETURN)` → OPEN_DRONEPORT (если крыша закрыта) → ждать BOARDING_REQUEST → CLOSE_DRONEPORT |
| COORDINATE_NED (CMD 29) | Прямая ретрансляция на `radio_link` без ACK и постановки в очередь. Переполнение не возникает — вызов немедленный |

---


# 7. Протокол связи с БПЛА (radio_link, USART)

## 7.1. Физика и архитектура каналов

Порт: `/dev/ttyUSB0` @ 115200 бод. Протокол: **CRSF (CrossFire)**. Связь двусторонняя: OrangePi ↔ радиопередатчик ↔ БПЛА.

В системе существуют **два логических канала**:

|**Канал**|**Стороны**|**Назначение**|
|---|---|---|
|Дрон ↔ Дронпорт|`0xC8` ↔ `0x80`|Телеметрия, посадочные запросы, команды управления полётом|
|Дрон ↔ Станция навигации|`0xC8` ↔ `0xEE`|Результаты миссий (DEMO_RESULT, DIAG_RESULT, TARGET, RETURN_DRONE)|

OrangePi выступает **ретранслятором**: пакеты канала «Дрон ↔ Станция навигации» принимаются через радиоканал и немедленно пробрасываются серверу через UDP.

### Схема адресации

|**Устройство**|**Адрес (HEX)**|**Описание**|
|---|---|---|
|Дрон|`0xC8`|Полётный контроллер БПЛА|
|Дронпорт|`0x80`|Станция базирования (OrangePi)|
|Станция навигации|`0xEE`|Пульт управления / навигационная станция|

---

## 7.2. Структура пакета CRSF

|**Поле**|**Размер**|**Описание**|
|---|---|---|
|ADDR|1 байт|Адрес получателя (см. схему адресации)|
|LEN|1 байт|Длина пакета: TYPE + PAYLOAD + CRC8|
|TYPE|1 байт|Идентификатор типа сообщения (код команды)|
|PAYLOAD|0–60 байт|Полезная нагрузка|
|CRC8|1 байт|Контрольная сумма, полином **0xD5**|

> **Формула CRC8:** вычисляется по полиному 0xD5 над полями TYPE + PAYLOAD.

---

## 7.3. Команды OrangePi → БПЛА (канал Дронпорт → Дрон)

ADDR получателя: `0xC8` (Дрон).

|**TYPE (HEX)**|**Имя**|**Размер PAYLOAD (байт)**|**Описание**|
|---|---|---|---|
|`0x11`|COMBAT_MODE|13|X,Y,Z int32 ×10⁷ + резерв|
|`0x12`|TARGET_INTERCEPTION|13|X,Y,Z (Z = высота перехвата, задаётся оператором)|
|`0x13`|SECTOR_SEARCH|16|X,Y,Z + azimuth_center uint16 (0–359°) + azimuth_width uint8 (1–180°) + резерв|
|`0x14`|DRONE_FLIGHT|12|num_src uint8 + num_dst uint8 + X,Y int32 ×10⁷ + резерв|
|`0x15`|PRE_FLIGHT|0|Нет данных|
|`0x16`|DIAGNOSTIC_FLIGHT|0|Нет данных|
|`0x1A`|STOP|0|БПЛА зависает на месте. **КРИТИЧЕСКИЙ приоритет**|
|`0x1B`|RETURN|0|БПЛА возвращается на базу. **КРИТИЧЕСКИЙ приоритет**|

> ⚠️ **DEMO_MODE и COORDINATE_NED отсутствуют в протоколе CRSF. Необходимо уточнить у заказчика.**

---

## 7.4. Сообщения БПЛА → OrangePi (канал Дрон → Дронпорт)

ADDR получателя: `0x80` (Дронпорт).

|**TYPE (HEX)**|**Имя**|**Размер PAYLOAD (байт)**|**Частота**|
|---|---|---|---|
|`0x1E`|TELEMETRY_FAST|53|200 Гц|
|`0x1F`|TELEMETRY_SLOW|24|10 Гц|
|`0x20`|SOS|13|По событию (критично)|
|`0x21`|BOARDING_REQUEST|1|По событию|
|`0x22`|ERROR|4×N|По событию (критично)|

---

## 7.5. Сообщения БПЛА → OrangePi (канал Дрон → Станция навигации)

ADDR получателя: `0xEE` (Станция навигации). OrangePi принимает эти пакеты и ретранслирует серверу через UDP.

|**TYPE (HEX)**|**Имя**|**Размер PAYLOAD (байт)**|**Частота**|
|---|---|---|---|
|`0x28`|TELEMETRY_FAST|41|200 Гц|
|`0x29`|TELEMETRY_SLOW|24|10 Гц|
|`0x2B`|DEMO_RESULT|16|По событию|
|`0x2D`|DIAG_RESULT|13|По завершении|
|`0x2E`|TARGET|5|По событию|

---

## 7.6. Структура PAYLOAD по типам сообщений

### TELEMETRY_FAST (TYPE=`0x1E`, канал Дрон→Дронпорт, 53 байта)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0–3|Линейное ускорение X|Int32|
|4–7|Линейное ускорение Y|Int32|
|8–11|Линейное ускорение Z|Int32|
|12–15|Кватернион q0|Int32|
|16–19|Кватернион q1|Int32|
|20–23|Кватернион q2|Int32|
|24–27|Кватернион q3|Int32|
|28–31|Динамическое смещение X|Int32|
|32–35|Динамическое смещение Y|Int32|
|36–39|Динамическое смещение Z|Int32|
|40–43|Координата X дрона (NED)|Int32|
|44–47|Координата Y дрона (NED)|Int32|
|48–51|Координата Z дрона (NED)|Int32|
|52|Флаги GPS и акселерометра|Uint8 (биты: 0=GPS ошибка, 1=акселерометр, 2=смещение)|
|53|Резерв|—|

### TELEMETRY_SLOW (TYPE=`0x1F`, канал Дрон→Дронпорт, 24 байта)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0–1|Угловая скорость X|Int16|
|2–3|Угловая скорость Y|Int16|
|4–5|Угловая скорость Z|Int16|
|6–7|Крен|Int16|
|8–9|Тангаж|Int16|
|10–11|Рысканье|Int16|
|12|Заряд батареи|Uint8|
|13–14|Ток потребления|Uint16|
|15–16|Текущая скорость|Uint16|
|17–18|GPS координата X|Int16|
|19–20|GPS координата Y|Int16|
|21|Флаг GPS и ошибки|Uint8 (бит 0=GPS валиден, бит 1=ошибка, биты 2–7=резерв)|
|22|Флаг режима работы дрона|Uint8 (1=Боевой, 2=Перехват, 3=Демо, 4=Поиск, 5=Диаг.полёт, 6=Перелёт)|
|23|RSSI|Int8 (от −128 до 0 dBm)|
|24|Резерв|—|

### SOS (TYPE=`0x20`, канал Дрон→Дронпорт, 13 байт)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0|Флаг активности GPS|Uint8 (всегда 1 при SOS)|
|1–4|Координата X (широта)|Int32|
|5–8|Координата Y (долгота)|Int32|
|9–12|Координата Z (высота над уровнем моря)|Int32|
|13|Резерв|—|

### BOARDING_REQUEST (TYPE=`0x21`, канал Дрон→Дронпорт, 1 байт)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0|Запрос посадки|Uint8|

### ERROR (TYPE=`0x22`, канал Дрон→Дронпорт, 4×N байт)

Структура идентична `ErrorEntry.to_bytes()` из `error_handler.py`: `[error_class | subsystem | code | flags]` × N ошибок.

### DEMO_RESULT (TYPE=`0x2B`, канал Дрон→Станция, 16 байт)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0|Флаги результата|Uint8 (бит 0=успех атаки, бит 1=дрон возвращается, биты 2–7=резерв)|
|1–4|Координата X поражения (локальная СК)|Int32|
|5–8|Координата Y поражения (локальная СК)|Int32|
|9–12|Координата Z поражения (локальная СК)|Int32|
|13|Резерв|—|

### DIAG_RESULT (TYPE=`0x2D`, канал Дрон→Станция, 13 байт)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0|Флаги диагностики|Uint8 (бит 0=диагностика успешна, бит 1=дрон готов к работе, биты 2–7=резерв)|
|1–4|Байт ошибки|Структура ошибок (см. Раздел 8)|
|5|Резерв|—|

### TARGET (TYPE=`0x2E`, канал Дрон→Станция, 5 байт)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0|Наличие цели|Uint8 (0=нет цели, 1=обнаружена, 2=ошибка распознавания)|

### RETURN_DRONE (канал Дрон→Станция)

|**Байты**|**Название**|**Тип**|
|---|---|---|
|0–1|Напряжение аккумулятора|Uint16|
|2|Причина возврата|Uint8|
|3|Резерв|—|

> ⚠️ **TYPE-код RETURN_DRONE в протоколе CRSF явно не указан. Необходимо уточнить у заказчика.**

---

## 7.7. Механизм подтверждения (ACK/NACK)

Для критических команд используется механизм подтверждения доставки.

|**Код**|**Значение**|
|---|---|
|`0xF1`|ACK — успешное получение и валидность пакета|
|`0xF2`|NACK — ошибка (неверный формат, невозможное состояние)|

- Таймаут ожидания ACK: **50 мс**
- Количество повторов: **5**
- Применяется к командам с приоритетом **КРИТИЧЕСКИЙ** и **ВАЖНЫЙ**: STOP, RETURN, SOS, ERROR, COMBAT_MODE, TARGET_INTERCEPTION, BOARDING_REQUEST

---

## 7.8. Классификация приоритетов сообщений

|**Приоритет**|**Сообщения**|**Требование**|
|---|---|---|
|КРИТИЧЕСКИЙ|SOS, STOP, RETURN, ERROR|Требуют подтверждения ACK|
|ВАЖНЫЙ|TARGET, COMBAT_MODE, BOARDING_REQUEST|Передача до получения первого ACK|
|ИНФОРМАЦИОННЫЙ|TELEMETRY_FAST, TELEMETRY_SLOW|Потеря отдельных пакетов не влияет на безопасность|

---

## 7.9. Нагрузка на канал связи

Скорость канала CRSF: 416 666 бит/с, эффективная пропускная способность ~40 Кбайт/сек.

|**Тип**|**Размер пакета**|**Частота**|**Байт/сек**|**Нагрузка %**|
|---|---|---|---|---|
|TELEMETRY_FAST|45 байт|200 Гц|9 000|22.5%|
|TELEMETRY_SLOW|28 байт|10 Гц|280|0.7%|
|STATUS/Other|10 байт|5 Гц|50|0.1%|
|**ИТОГО**|—|—|**9 330**|**~23.3%**|

Пиковая нагрузка (SOS + ERROR с 3 ошибками): +340 байт/сек. Суммарная нагрузка остаётся в пределах **25%**, запас — 75%.
# 8. Обработка ошибок

## 8.1. Коды ошибок (ERROR_CODE_MAP в error_handler.py)

| **Строковый код** | **CLASS** | **Подсистема** | **Код** | **Описание** |
|---|---|---|---|---|
| MAINS_LOST | POWER | DRONEPORT | 0x01 | Потеря питания 220В |
| BATTERY_LOW | POWER | DRONEPORT | 0x02 | АКБ 12В < 11.0В (BATTERY_LOW) |
| SHUTTER_BLOCKED_OPENED | MECHANICS | DRONEPORT | 0x10 | Крыша заклинила в открытом положении |
| SHUTTER_BLOCKED_CLOSED | MECHANICS | DRONEPORT | 0x11 | Крыша заклинила в закрытом положении |
| SHUTTER_TIMEOUT | MECHANICS | DRONEPORT | 0x12 | Крыша не открылась/закрылась за таймаут (ESC Hobbywing) |
| TABLE_BLOCKED_UP | MECHANICS | DRONEPORT | 0x13 | Стол заблокирован вверху (TB6600 №1 или №2) |
| TABLE_BLOCKED_DOWN | MECHANICS | DRONEPORT | 0x14 | Стол заблокирован внизу |
| TABLE_TIMEOUT | MECHANICS | DRONEPORT | 0x15 | Стол не поднялся/опустился за таймаут |
| ERROR_HEATING | MECHANICS | DRONEPORT | 0x16 | Ошибка нагревательного элемента (SSR/транзистор) |
| DRONE_NOT_DETECTED | COMMUNICATION | DRONEPORT | 0x20 | БПЛА не обнаружен (нет telemetry > 15 сек) |
| DRONE_NO_RESPONSE | COMMUNICATION | DRONEPORT | 0x21 | Нет ответа от БПЛА (нет telemetry 5–15 сек) |
| TEMP_SENSOR_FAIL | SENSORS | DRONEPORT | 0x30 | Ошибка датчика DHT22 |
| TEMP_OUT_OF_RANGE | ENVIRONMENT | DRONEPORT | 0x31 | Температура вне допустимого диапазона |
| MAINTENANCE_MODE | SAFETY | DRONEPORT | 0x40 | Активен режим технического обслуживания |
| UNAUTHORIZED_COMMAND | SECURITY | DRONEPORT | 0x50 | Неизвестная/неавторизованная команда |
| BATTERY_CRITICAL | POWER | DRONE | 0x02 | АКБ БПЛА критически низкий |
| ESC_FAIL | MECHANICS | DRONE | 0x11 | Ошибка регулятора скорости |
| POSITION_LOST | NAVIGATION | DRONE | 0x20 | БПЛА потерял позицию |
| POSITION_JUMP | NAVIGATION | DRONE | 0x21 | Скачок координат (GPS-подавление?) |
| CAMERA_FAIL | SENSORS | DRONE | 0x30 | Отказ камеры БПЛА |
| THERMAL_FAIL | SENSORS | DRONE | 0x31 | Отказ тепловизора БПЛА |
| TARGET_LOST | SOFTWARE | DRONE | 0x40 | Внезапная потеря цели |
| LINK_NAV_LOST | COMMUNICATION | DRONE | 0x50 | Потеря связи с навигационной станцией |
| STATION_OVERHEAT | HARDWARE | DRONE | 0x41 | Перегрев БПЛА/станции |

## 8.2. Логика повторных попыток

| **Ситуация** | **Действие** | **Лимит** | **Итог при провале** |
|---|---|---|---|
| Ошибка CRC UART-пакета STM32 | Повторить запрос | 3 | ERROR COMMUNICATION |
| Концевик не в ожидаемом состоянии | CMD + ждать + проверить снова | 3 | report_error('SHUTTER_TIMEOUT' / 'TABLE_TIMEOUT') |
| Нет ответа UDP от сервера | Буферизовать ошибки | — | Автономный режим; flush_buffer при восстановлении |
| GPS без фикса | Ждать до `sensor_timeouts.gps_fix` = 20 сек (из hardware.yaml) | 1 раз | POSITION_LOST + ERROR |
| Нет телеметрии БПЛА 5–15 сек | DRONE_NO_RESPONSE (WARNING) | — | Продолжение работы |
| Нет телеметрии БПЛА > 15 сек | DRONE_NOT_DETECTED (CRITICAL, emergency_stop=True) | — | ERROR серверу + перейти в IDLE |

---

# 9. Сценарии работы системы

Все многошаговые сценарии управляются методом `_run_scenario_steps()` класса `CommandHandlers` и описываются в `scenarios.json`. Об��значения: `STM32(N)` = send_action(N); `HALL[X]` = read_hall_sensors() бит X (концевик) должен быть 1; `RADIO(CMD)` = radio_link.send_command; `WAIT(key)` = т��ймаут из hardware.yaml.

## 9.1. OPEN_DRONEPORT — открытие

Триггер: CMD=1. Результат: крыша открыта, стол вверху, LED включена, лапки разжаты (зарядка отключена).

| **Шаг** | **Действие** | **Верификация** | **Ошибка при провале** |
|---|---|---|---|
| 0 | ACK серверу | — | — |
| 1 | STM32(17) — открыть крышу (PWM → 2 ESC Hobbywing → 2 актуатора синхронно) | WAIT(open_roof=**30с**) → HALL[0]=1 (крыша открыта) | SHUTTER_TIMEOUT |
| 2 | STM32(13) — поднять стол (STEP/DIR → TB6600 №1 и TB6600 №2 синхронно → 2 шаговика) | WAIT(raise_table=**20с**) → HALL[2]=1 (стол поднят) | TABLE_TIMEOUT |
| 3 | STM32(7) — включить LED-ленту (подсветка посадочной площадки) | WAIT(default=**0с**, моментально) | ERROR_HEATING (освещение) |
| 4 | STM32(15) — открыть лапки (STEP/DIR → TB6600 №2 → 1 шаговик → 4 лапки). Зарядка отключается | WAIT(open_clamps=8с). Бит 6 должен стать 0 | MECHANICS |
| 5 | → СЕРВЕР(30 RESULT_STATUS_SHUTTERS): DATA[0]=1 | — | DATA[0]=−1 + ERROR(48) при любом провале |

## 9.2. CLOSE_DRONEPORT — закрытие

Триггер: CMD=2. Результат: лапки сжаты (зарядка активна), LED выключена, стол внизу, крыша закрыта. Порядок строго обратный открытию.

| **Шаг** | **Действие** | **Верификация** | **Ошибка** |
|---|---|---|---|
| 0 | ACK серверу | — | — |
| 1 | STM32(16) — закрыть лапки (TB6600 №2 реверс → 4 лапки сжимают БПЛА). Зарядка активируется при смыкании | WAIT(close_clamps=8с) → HALL[6]=1 (лапки сжаты) | MECHANICS |
| 2 | STM32(8) — выключить LED-ленту | WAIT(default=**0с**, моментально) | — |
| 3 | STM32(14) — опустить стол (TB6600 №1 и TB6600 №2 реверс синхронно) | WAIT(lower_table=**20с**) → HALL[3]=1 (стол опущен) | TABLE_TIMEOUT |
| 4 | STM32(18) — закрыть крышу (PWM → 2 ESC Hobbywing реверс) | WAIT(close_roof=**30с**) → HALL[1]=1 (крыша закрыта) | SHUTTER_TIMEOUT |
| 5 | → СЕРВЕР(30 RESULT_STATUS_SHUTTERS): DATA[0]=0 | — | DATA[0]=−1 + ERROR(48) |

## 9.3. PRE_FLIGHT — предполётная подготовка

Триггер: CMD=28. Abort on error: true. GPS-таймаут: `sensor_timeouts.gps_fix` = 20 сек (из `hardware.yaml`). Таймаут ожидания DIAG_RESULT: `radio_timeouts.diag_result` = 20 сек.

| **Шаг** | **Действие** | **Ошибка при провале** |
|---|---|---|
| 0 | ACK серверу | — |
| 1 | `usb_sensors.get_coordinates()` — ждать GPS-фикс до 20 сек (`gps_fix` из hardware.yaml). `require_fix=true` | NAVIGATION: POSITION_LOST → NACK(3) + ERROR |
| 2 | `uart_stm32.read_voltage()` — проверить ≥ 11.0В (`battery_min_voltage`) | POWER: BATTERY_LOW |
| 3 | `uart_stm32.read_hall_sensors()` — исходное положение: концевик 2 (крыша закрыта) И концевик 4 (стол внизу) И концевик 7 (лапки сжаты) | MECHANICS |
| 4 | `radio_link.send_command(CMD=28)` — отправить БПЛА команду PRE_FLIGHT | DRONE_NO_RESPONSE |
| 5 | Ждать `DIAG_RESULT (CMD=45)` от БПЛА, таймаут 20 сек | DRONE_NO_RESPONSE |
| 6 | → СЕРВЕР(45 DIAG_RESULT) | — |

> _Шаг проверки `radio_link.is_drone_connected()` (из предыдущей редакции спецификации) **не реализован** в текущем `scenarios.json`. Связь с БПЛА проверяется косвенно: если `radio_link=None` — шаги 4–5 пропускаются с заглушкой._

## 9.4. DIAGNOSTIC — диагностика дронпорта

Триггер: CMD=3. Abort on error: false (собирать все данные даже при частичных ошибках).

| **Шаг** | **Действие** | **Результат** |
|---|---|---|
| 0 | ACK серверу | — |
| 1 | `uart_stm32.read_hall_sensors()` | Положение крыши (концевики 1,2), стола (3,4), заслонок (5,6), лапок (7) |
| 2 | `uart_stm32.read_voltage()` | Напряжение резервного АКБ 12В LiFePO4 |
| 3 | `uart_stm32.read_dht22()` | Температура и влажность внутри корпуса дронпорта |
| 4 | `uart_weather.read_weather()` | Температура снаружи, скорость и направление ветра (Arduino метеостанция по USB) |
| 5 | `usb_sensors.get_coordinates()` | GPS-позиция дронпорта |
| 6 | → СЕРВЕР(31) + СЕРВЕР(33) | RESULT_DIAGNOSTIC + RESULT_EXTERNAL_PARAM |

## 9.5. DEMO_MODE — демонстрационный полёт

Триггер: CMD=22. DATA: X,Y,Z цели (int32 ×10⁷).

| **Шаг** | **Действие** | **Примечание** |
|---|---|---|
| 0 | ACK серверу | — |
| 1 | sub_scenario: PRE_FLIGHT | При провале — NACK + ERROR + стоп |
| 2 | sub_scenario: OPEN_DRONEPORT | Крыша, стол, LED, лапки |
| 3 | RADIO(DEMO_MODE, X,Y,Z) | БПЛА начинает автономный полёт к цели |
| 4 | Мониторинг: TELEMETRY_SLOW(41) → СЕРВЕР(41) | До DEMO_RESULT или таймаут 5 мин |
| 5 | DEMO_RESULT(43) от БПЛА → СЕРВЕР(43) | Флаги успеха + координаты |
| 6 | Ждать BOARDING_REQUEST(44) | Таймаут 3 мин. Нет ответа → DRONE_NO_RESPONSE |
| 7 | sub_scenario: CLOSE_DRONEPORT | Лапки, LED, стол, крыша |

## 9.6. COMBAT_MODE — боевой режим

Триггер: CMD=20. DATA: X,Y,Z цели. Поведение аналогично DEMO_MODE, но с полным мониторингом боевых событий.

| **Шаг** | **Действие** |
|---|---|
| 0 | ACK + PRE_FLIGHT + OPEN_DRONEPORT |
| 1 | RADIO(COMBAT_MODE, X,Y,Z) |
| 2 | Мониторинг: TELEMETRY_FAST(40) + TELEMETRY_SLOW(41) → СЕРВЕР |
| 3 | Ретрансляция боевых событий: TARGET(46)→СЕРВЕР(46); SOS(42)→СЕРВЕР(42); RETURN_DRONE(47)→СЕРВЕР(47) |
| 4 | BOARDING_REQUEST(44) → CLOSE_DRONEPORT |

## 9.7. TARGET_INTERCEPTION — перехват цели

Триггер: CMD=21. DATA: X,Y,Z (Z задаётся оператором с учётом высоты цели). Логика идентична COMBAT_MODE. Отличие только в данных: Z-координата выше для перехвата на высоте цели.

## 9.8. SECTOR_SEARCH — секторный поиск

Триггер: CMD=23. DATA: X,Y,Z + azimuth_center (uint16, 0–359°) + azimuth_width (uint8, 1–180°).

| **Шаг** | **Действие** |
|---|---|
| 0 | ACK + PRE_FLIGHT + OPEN_DRONEPORT |
| 1 | RADIO(SECTOR_SEARCH, X,Y,Z, azimuth_center, azimuth_width) |
| 2 | Мониторинг: TELEMETRY_SLOW(41) → СЕРВЕР(41) |
| 3 | TARGET(46) обнаружена → немедленно СЕРВЕР(46) |
| 4 | BOARDING_REQUEST(44) → CLOSE_DRONEPORT |

## 9.9. DIAGNOSTIC_FLIGHT — диагностический полёт

Триггер: CMD=24. БПЛА выполняет автономный тестовый полёт и возвращается.

| **Шаг** | **Действие** | **Таймаут** |
|---|---|---|
| 0 | ACK + PRE_FLIGHT + OPEN_DRONEPORT | — |
| 1 | RADIO(DIAGNOSTIC_FLIGHT) | — |
| 2 | Мониторинг TELEMETRY_SLOW(41) → СЕРВЕР(41) | 5 мин |
| 3 | DIAG_RESULT(45) → СЕРВЕР(45) | — |
| 4 | BOARDING_REQUEST(44) → CLOSE_DRONEPORT | 3 мин |

## 9.10. DRONE_FLIGHT — перелёт между дронпортами

Триггер: CMD=25. DATA: num_src (uint8), num_dst (uint8), X,Y целевого дронпорта (int32 ×10⁷).

| **Шаг** | **Действие** |
|---|---|
| 0 | ACK. Проверить: num_src == собственный droneport_id. Если нет → NACK(3) |
| 1 | PRE_FLIGHT + OPEN_DRONEPORT |
| 2 | RADIO(DRONE_FLIGHT, num_dst, X_dst, Y_dst) |
| 3 | Мониторинг TELEMETRY_SLOW(41) → СЕРВЕР(41). Ретрансляция RETURN_DRONE(47)→СЕРВЕР(47) |
| 4 | BOARDING_REQUEST(44) → CLOSE_DRONEPORT стартового дронпорта |

## 9.11. STOP — экстренная остановка

> ⚡ **Приоритет: НАИВЫСШИЙ. Обрабатывается немедленно вне очереди.**

| **Шаг** | **Действие** |
|---|---|
| 0 | ACK серверу немедленно |
| 1 | `_clear_queue()` — сброс всей очереди команд |
| 2 | `radio_link.send_command(CMD=26)` — БПЛА зависает на текущей позиции |
| 3 | Механизмы дронпорта остаются в текущем положении. Система переходит в режим ожидания (пустая очередь) |

## 9.12. RETURN — возврат на базу

> ⚡ **Приоритет: НАИВЫСШИЙ. Аналогично STOP, но с организацией приёма БПЛА.**

| **Шаг** | **Действие** |
|---|---|
| 0 | ACK + `_clear_queue()` — сброс очереди |
| 1 | `radio_link.send_command(CMD=27)` — БПЛА начинает RTH независимо от текущей миссии |
| 2 | Если дронпорт закрыт (HALL[1]=1): выполнить сценарий OPEN_DRONEPORT для приёма |
| 3 | Ждать `BOARDING_REQUEST (CMD=44)`, таймаут `radio_timeouts.return_receive` = 20 сек → CLOSE_DRONEPORT |

## 9.13. Автоматические фоновые задачи (watchdog)

| **Задача** | **Условие / Период** | **Действие** |
|---|---|---|
| STATUS heartbeat | Каждые 420 сек | udp_tx.send_status_droneport(ready=True) |
| UART watchdog | Каждые 30 сек | uart_stm32.read_voltage(). 3 неудачи подряд → DRONE_NO_RESPONSE (WARNING) |
| Мониторинг АКБ 12В | Каждые 5 мин | read_voltage(). < 11.0В → BATTERY_LOW; < 9.5В → BATTERY_CRITICAL (emergency_stop) |
| Антиобледенение вибромоторами | T < −10°C (из STM32 DHT22 или Arduino метеостанция) И раз в 30 мин | STM32(CMD 1) — включить 3 вибромотора на 10 сек → STM32(CMD 2) |
| Видеопоток USB-камеры | Постоянно с момента запуска | subprocess: ffmpeg/gstreamer → поток на server_ip:video_port |

---

# 10. Файл scenarios.json — эталон

Типы шагов:

| **Тип** | **Ключевые параметры** | **Описание** |
|---|---|---|
| `stm32_action` | `action_code`, `verify_hall`, `expected_hall_bit`, `bit_value`, `timeout_key`, `error_code` | Команда STM32 + опциональная верификация одного бита концевого датчика |
| `stm32_request` | `system_part` (1–3), `store_as`, `min_value?`, `assert_bits?`, `error_code?` | Запрос данных у STM32 (концевики/напряжение/DHT22) |
| `radio_command` | `cmd`, `data_source` | Команда БПЛА. data_source: `"scenario_input"`, `"stored:ключ"` или `null` |
| `wait_radio` | `expected_cmd`, `timeout_key`, `store_as?`, `relay_cmds?` | Ждать CMD от БПЛА. `relay_cmds`: ретранслировать серверу в процессе |
| `usb_sensor` | `sensor` (`gps`), `store_as`, `timeout_key`, `require_fix?`, `error_code?` | Получить данные USB-датчика (GPS) |
| `weather_request` | `store_as`, `timeout_key`, `error_code?` | Запрос метеостанции Arduino по USB (0x01 → 8 байт) |
| `send_server` | `cmd`, `data_source` | Отправить пакет серверу. data_source: `"stored:key1,key2"` или `{"shutters": 0/1}` |
| `sub_scenario` | `name` | Встроить другой сценарий (рекурсивно, с общим `store`) |

> ⚠️ **Ключевой параметр ожидания в шагах `wait_radio` и `usb_sensor` — `timeout_key` (строка-ключ в `hardware.yaml`), а не `timeout_sec` (число секунд).** Это обеспечивает централизованное управление таймаутами через `hardware.yaml`.

Актуальное содержимое `config/scenarios.json` — см. файл в репозитории. Он является единственным авторитетным источником шагов сценариев. Ниже приведён нормативный эталон структуры:

```json
{
  "OPEN_DRONEPORT": {
    "description": "Открыть крышу → поднять стол → включить LED → открыть лапки (зарядка откл.)",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "stm32_action",
        "description": "Открыть крышу (PWM → ESC Hobbywing × 2 актуатора синхронно)",
        "action_code": 17, "verify_hall": true, "expected_hall_bit": 0, "bit_value": 1,
        "timeout_key": "open_roof", "error_code": "SHUTTER_TIMEOUT" },
      { "step_id": 2, "type": "stm32_action",
        "description": "Поднять стол (STEP/DIR → TB6600 №1 и TB6600 №2 синхронно)",
        "action_code": 13, "verify_hall": true, "expected_hall_bit": 2, "bit_value": 1,
        "timeout_key": "raise_table", "error_code": "TABLE_TIMEOUT" },
      { "step_id": 3, "type": "stm32_action",
        "description": "Включить LED-ленту (подсветка посадочной площадки)",
        "action_code": 7, "verify_hall": false, "timeout_key": "default", "error_code": "ERROR_HEATING" },
      { "step_id": 4, "type": "stm32_action",
        "description": "Открыть лапки (TB6600 №2 → 1 шаговик → 4 лапки через передачу). Зарядка отключается",
        "action_code": 15, "verify_hall": true, "expected_hall_bit": 6, "bit_value": 0,
        "timeout_key": "open_clamps", "error_code": "MECHANICS" },
      { "step_id": 5, "type": "send_server",
        "description": "Отправить серверу: крыша открыта (RESULT_STATUS_SHUTTERS, CMD=30)",
        "cmd": 30, "data_source": { "shutters": 1 } }
    ]
  },

  "CLOSE_DRONEPORT": {
    "description": "Закрыть лапки (зарядка вкл.) → выкл. LED → опустить стол → закрыть крышу. Строго обратный порядок",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "stm32_action",
        "description": "Закрыть лапки (TB6600 №2 реверс → 4 лапки сжимают БПЛА). При смыкании — зарядка через контакты лапок",
        "action_code": 16, "verify_hall": true, "expected_hall_bit": 6, "bit_value": 1,
        "timeout_key": "close_clamps", "error_code": "MECHANICS" },
      { "step_id": 2, "type": "stm32_action",
        "description": "Выключить LED-ленту",
        "action_code": 8, "verify_hall": false, "timeout_key": "default" },
      { "step_id": 3, "type": "stm32_action",
        "description": "Опустить стол (STEP/DIR → TB6600 №1 и TB6600 №2 реверс синхронно)",
        "action_code": 14, "verify_hall": true, "expected_hall_bit": 3, "bit_value": 1,
        "timeout_key": "lower_table", "error_code": "TABLE_TIMEOUT" },
      { "step_id": 4, "type": "stm32_action",
        "description": "Закрыть крышу (PWM → ESC Hobbywing × 2 реверс синхронно)",
        "action_code": 18, "verify_hall": true, "expected_hall_bit": 1, "bit_value": 1,
        "timeout_key": "close_roof", "error_code": "SHUTTER_TIMEOUT" },
      { "step_id": 5, "type": "send_server",
        "description": "Отправить серверу: крыша закрыта (RESULT_STATUS_SHUTTERS, CMD=30)",
        "cmd": 30, "data_source": { "shutters": 0 } }
    ]
  },

  "PRE_FLIGHT": {
    "description": "Предполётная проверка: GPS фикс, АКБ ≥ 11.0В, исходное положение механики, связь с БПЛА, диагностика БПЛА",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "usb_sensor", "sensor": "gps", "store_as": "gps",
        "timeout_key": "gps_fix", "require_fix": true, "error_code": "POSITION_LOST" },
      { "step_id": 2, "type": "stm32_request", "system_part": 2, "store_as": "voltage",
        "min_value": 11.0, "error_code": "BATTERY_LOW" },
      { "step_id": 3, "type": "stm32_request", "system_part": 1, "store_as": "hall",
        "assert_bits": { "1": 1, "3": 1, "6": 1 }, "error_code": "MECHANICS" },
      { "step_id": 4, "type": "radio_command", "cmd": 28, "data_source": null },
      { "step_id": 5, "type": "wait_radio", "expected_cmd": 45,
        "timeout_key": "diag_result", "store_as": "diag_result", "error_code": "DRONE_NO_RESPONSE" },
      { "step_id": 6, "type": "send_server", "cmd": 45, "data_source": "stored:diag_result" }
    ]
  },

  "DIAGNOSTIC": {
    "description": "Диагностика всех подсистем дронпорта. abort_on_error=false — собрать максимум данных даже при частичных ошибках",
    "abort_on_error": false,
    "steps": [
      { "step_id": 1, "type": "stm32_request", "system_part": 1, "store_as": "hall" },
      { "step_id": 2, "type": "stm32_request", "system_part": 2, "store_as": "voltage" },
      { "step_id": 3, "type": "stm32_request", "system_part": 3, "store_as": "dht22" },
      { "step_id": 4, "type": "weather_request", "store_as": "weather", "timeout_key": "weather" },
      { "step_id": 5, "type": "usb_sensor", "sensor": "gps", "store_as": "gps", "timeout_key": "gps_fix" },
      { "step_id": 6, "type": "send_server", "cmd": 31, "data_source": "stored:voltage,hall" },
      { "step_id": 7, "type": "send_server", "cmd": 33, "data_source": "stored:dht22,weather" }
    ]
  },

  "DEMO_MODE": {
    "description": "Демонстрационный полёт к цели (X,Y,Z int32 × 10^7) и автоматический возврат",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "sub_scenario", "name": "PRE_FLIGHT" },
      { "step_id": 2, "type": "sub_scenario", "name": "OPEN_DRONEPORT" },
      { "step_id": 3, "type": "radio_command", "cmd": 22, "data_source": "scenario_input" },
      { "step_id": 4, "type": "wait_radio", "expected_cmd": 43,
        "timeout_key": "demo_result", "store_as": "demo_result", "relay_cmds": [41, 46] },
      { "step_id": 5, "type": "send_server", "cmd": 43, "data_source": "stored:demo_result" },
      { "step_id": 6, "type": "wait_radio", "expected_cmd": 44, "timeout_key": "boarding_request" },
      { "step_id": 7, "type": "sub_scenario", "name": "CLOSE_DRONEPORT" }
    ]
  },

  "COMBAT_MODE": {
    "description": "Боевой режим: полный мониторинг. Ретранслируются TARGET, SOS, RETURN_DRONE",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "sub_scenario", "name": "PRE_FLIGHT" },
      { "step_id": 2, "type": "sub_scenario", "name": "OPEN_DRONEPORT" },
      { "step_id": 3, "type": "radio_command", "cmd": 20, "data_source": "scenario_input" },
      { "step_id": 4, "type": "wait_radio", "expected_cmd": 44,
        "timeout_key": "boarding_request", "relay_cmds": [40, 41, 42, 43, 46, 47] },
      { "step_id": 5, "type": "sub_scenario", "name": "CLOSE_DRONEPORT" }
    ]
  },

  "TARGET_INTERCEPTION": {
    "description": "Перехват цели. Z-координата задаётся оператором с учётом высоты цели. Логика идентична COMBAT_MODE",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "sub_scenario", "name": "PRE_FLIGHT" },
      { "step_id": 2, "type": "sub_scenario", "name": "OPEN_DRONEPORT" },
      { "step_id": 3, "type": "radio_command", "cmd": 21, "data_source": "scenario_input" },
      { "step_id": 4, "type": "wait_radio", "expected_cmd": 44,
        "timeout_key": "boarding_request", "relay_cmds": [40, 41, 42, 46, 47] },
      { "step_id": 5, "type": "sub_scenario", "name": "CLOSE_DRONEPORT" }
    ]
  },

  "SECTOR_SEARCH": {
    "description": "Секторный поиск. DATA: X,Y,Z + azimuth_center (uint16, 0–359°) + azimuth_width (uint8, 1–180°)",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "sub_scenario", "name": "PRE_FLIGHT" },
      { "step_id": 2, "type": "sub_scenario", "name": "OPEN_DRONEPORT" },
      { "step_id": 3, "type": "radio_command", "cmd": 23, "data_source": "scenario_input" },
      { "step_id": 4, "type": "wait_radio", "expected_cmd": 44,
        "timeout_key": "boarding_request", "relay_cmds": [41, 46] },
      { "step_id": 5, "type": "sub_scenario", "name": "CLOSE_DRONEPORT" }
    ]
  },

  "DIAGNOSTIC_FLIGHT": {
    "description": "Диагностический полёт: БПЛА выполняет автономный тестовый полёт и возвращается",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "sub_scenario", "name": "PRE_FLIGHT" },
      { "step_id": 2, "type": "sub_scenario", "name": "OPEN_DRONEPORT" },
      { "step_id": 3, "type": "radio_command", "cmd": 24, "data_source": null },
      { "step_id": 4, "type": "wait_radio", "expected_cmd": 45,
        "timeout_key": "diag_result", "store_as": "diag_result", "relay_cmds": [41] },
      { "step_id": 5, "type": "send_server", "cmd": 45, "data_source": "stored:diag_result" },
      { "step_id": 6, "type": "wait_radio", "expected_cmd": 44, "timeout_key": "boarding_request" },
      { "step_id": 7, "type": "sub_scenario", "name": "CLOSE_DRONEPORT" }
    ]
  },

  "DRONE_FLIGHT": {
    "description": "Перелёт между дронпортами. DATA: num_src (uint8) + num_dst (uint8) + X,Y целевого дронпорта (int32 × 10^7)",
    "abort_on_error": true,
    "steps": [
      { "step_id": 1, "type": "stm32_request", "system_part": 0, "store_as": "self_id_check",
        "assert_self_id": true, "error_code": "UNAUTHORIZED_COMMAND" },
      { "step_id": 2, "type": "sub_scenario", "name": "PRE_FLIGHT" },
      { "step_id": 3, "type": "sub_scenario", "name": "OPEN_DRONEPORT" },
      { "step_id": 4, "type": "radio_command", "cmd": 25, "data_source": "scenario_input" },
      { "step_id": 5, "type": "wait_radio", "expected_cmd": 44,
        "timeout_key": "drone_flight", "relay_cmds": [41, 47] },
      { "step_id": 6, "type": "sub_scenario", "name": "CLOSE_DRONEPORT" }
    ]
  }
}
```

---

# 11. Развёртывание и эксплуатация

## 11.1. Требования к окружению

| **Параметр**        | **Значение**                                                           |
| ------------------- | ---------------------------------------------------------------------- |
| ОС                  | Ubuntu 24.04 LTS (arm64)                                               |
| Python              | 3.12                                                                   |
| Группы пользователя | dialout, tty (для доступа к /dev/ttyS3, /dev/ttyUSB*, /dev/ttyACM*)              |
| Зависимости         | `pip install -r requirements.txt --break-system-packages`              |
| requirements.txt    | `pyserial==3.5  pyserial-asyncio==0.6  pynmea2==1.19.0  PyYAML==6.0.1` |

## 11.2. Настройка UART0 на OrangePi 5 Max
UART3 активируется через Device Tree Overlay `rk3588-uart3-m1.dtbo`. 
Overlay прописан в `/boot/extlinux/extlinux.conf` в строке `fdtoverlays`. 

Физические пины 40-pin header: 
- Пин 31 (GPIO3_B5) — TX → подключать к RX на STM32 
- Пин 33 (GPIO3_B6) — RX → подключать к TX на STM32 
- Пин 30 — GND → подключать к GND на STM32 
```bash 
# Проверить доступность порта: 
ls -la /dev/ttyS3 

# Добавить пользователя в группу dialout: 
sudo usermod -a -G dialout $USER 

# Loopback-тест (замкнуть пин 31 и 33): 
python3 -c " import serial, time s = serial.Serial('/dev/ttyS3', 115200, timeout=0.5) s.reset_input_buffer() s.write(bytes([0xBF, 0x40, 0x00, 0x40, 0xFF])) time.sleep(0.05) resp = s.read(64) print('OK' if resp == bytes([0xBF, 0x40, 0x00, 0x40, 0xFF]) else 'FAIL') s.close() " 
```

## 11.2.1. Подключение метеостанции Arduino Nano

Arduino Nano подключается по USB-кабелю к OrangePi. Чип CH340 на Arduino создаёт виртуальный COM-порт `/dev/ttyUSB1`.

> ⚠️ **Порядок USB-устройств:** радиопередатчик БПЛА должен быть `/dev/ttyUSB0`, метеостанция — `/dev/ttyUSB1`. Если порты путаются, настроить через udev-правила по VID:PID.

```bash
# Проверить доступность порта:
ls -la /dev/ttyUSB1

# Тест связи с Arduino (отправить 0x01, прочитать 8 байт):
python3 -c "
import serial, struct, time
s = serial.Serial('/dev/ttyUSB1', 115200, timeout=1.0)
time.sleep(2)  # Arduino ресетится при подключении
s.reset_input_buffer()
s.write(bytes([0x01]))
time.sleep(0.1)
resp = s.read(8)
if len(resp) == 8:
    wind_dir, wind_spd, temp_raw, hum = struct.unpack('<HHHH', resp)
    print(f'Dir={wind_dir}° Spd={wind_spd/10:.1f}m/s Temp={(temp_raw-1000)/10:.1f}°C Hum={hum/10:.1f}%')
else:
    print(f'FAIL: got {len(resp)} bytes')
s.close()
"
```

## 11.3. Запуск и тестирование

```bash
# Ручной запуск (debug.echo_mode: true в network.yaml):
python3 src/main.py

# В другом терминале — эмулятор сервера:
python3 tests/udp_writer.py

# Или сниффер входящих пакетов:
python3 tests/udp_listener.py
```

## 11.4. Systemd-юнит (systemd_service.service)

```ini
[Unit]
Description=Droneport Gateway Software
After=network.target

[Service]
Type=simple
User=droneport
WorkingDirectory=/opt/droneport
ExecStart=/usr/bin/python3 /opt/droneport/src/main.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/opt/droneport/logs/system.log
StandardError=append:/opt/droneport/logs/system.log

[Install]
WantedBy=multi-user.target
```

```bash
# Активация:
sudo systemctl enable droneport && sudo systemctl start droneport
```

---

# 12. Справочные таблицы

## 12.1. Числовые константы

| **Константа**         | **Значение**       | **Описание**                                          |
| --------------------- | ------------------ | ----------------------------------------------------- |
| SUBSYSTEM_ID          | 2001               | ID подсистемы в UDP-пакетах (uint16 Little Endian)    |
| DLE / STX / ETX       | 0x10 / 0x02 / 0x03 | Маркеры UDP-кадра                                     |
| ACK / NACK            | 0xF1 / 0xF2        | Квитанции                                             |
| BYTE_START_STM32      | 0xBF               | Маркер начала UART-пакета STM32                       |
| BYTE_END_STM32        | 0xFF               | Маркер конца UART-пакета STM32                        |
| FRAME_START_RADIO     | 0xAA, 0x55         | Маркер начала radio_link пакета                       |
| FRAME_END_RADIO       | 0xCC               | Маркер конца radio_link пакета                        |
| UART_BAUDRATE_STM32   | 115200             | OrangePi /dev/ttyS3 ↔ STM32 USART1                    |
| UART_BAUDRATE_RADIO   | 115200             | OrangePi /dev/ttyUSB0 ↔ радиопередатчик               |
| GPS_BAUDRATE          | 9600               | VK-162 @ /dev/ttyACM0                                 |
| UART_BAUDRATE_WEATHER | 115200             | OrangePi /dev/ttyUSB1 ↔ Arduino Nano метеостанция      |
| WEATHER_REQUEST_BYTE  | 0x01               | Байт запроса метеоданных от OrangePi к Arduino         |
| WEATHER_RESPONSE_LEN  | 8                  | Длина ответа Arduino (байт)                            |
| INTER_BYTE_TIMEOUT_MS | 100                | Межбайтовый таймаут STM32 UART                        |
| MAX_RETRIES           | 3                  | Повторных попыток (CRC/механика)                      |
| STATUS_INTERVAL_SEC   | 420                | Heartbeat STATUS_DRONEPORT (7 мин)                    |
| MAX_DATA_UDP          | 71                 | Макс. байт DATA в UDP-пакете                          |
| BATTERY_12V_DIVIDER   | 1/11               | Коэф. делителя (R1=10кОм, R2=1кОм). U_real = raw × 11 |
| BATTERY_MIN_V         | 11.0               | Порог BATTERY_LOW для 12В LiFePO4                     |
| BATTERY_CRITICAL_V    | 9.5                | Порог BATTERY_CRITICAL                                |
| VIBRO_COUNT           | 3                  | Количество вибромоторов                               |
| VIBRO_TEMP_THRESHOLD  | −10.0°C            | Температура включения вибромоторов                    |
| VIBRO_INTERVAL_SEC    | 1800               | Интервал включения вибромоторов (30 мин)              |
| VIBRO_DURATION_SEC    | 10                 | Длительность одного включения                         |
| MAX_DATA_STM32        | 100                | макс. длина DATA в UART-пакете STM32                  |
| NACK_STM32            | 0b11000000         | тип квитанции ошибки                                  |
| ACK_STM32             | 0b01000000         | тип квитанции успеха                                  |

## 12.2. Глоссарий

| **Термин** | **Определение** |
|---|---|
| OrangePi | Orange Pi 5 Max — главный вычислительный узел дронпорта |
| STM32 | STM32F401CUU6 — микроконтроллер управления всей силовой электроникой и механикой |
| ESC Hobbywing | Electronic Speed Controller — регулятор привода актуаторов крыши. Управляется PWM от STM32. 2 шт., работают синхронно |
| TB6600 | Драйвер шагового двигателя. TB6600 №1 и TB6600 №2: каждый управляет одним шаговиком стола; оба получают одинаковые STEP/DIR сигналы от STM32 и работают синхронно. TB6600 №3: управляет одним шаговиком лапок (все 4 лапки через механическую передачу) |
| L298N | Драйвер H-bridge. Управляет мотором заслонок вентиляторов (открыть/закрыть) |
| SSR | Solid State Relay — твердотельное реле. Управляет нагревательными элементами (220В). Два контура: воздух (5 эл.) и крыша (6 эл.) |
| Лапки | 4 сегментных зажима в форме дуги окружности, охватывающих цилиндрический корпус БПЛА. Управляются одним шаговиком (TB6600 №2) через механическую передачу. При смыкании активируется зарядка через контактные площадки |
| Концевой датчик (концевик) | Физическая кнопка-концевик для верификации положения механизмов. В системе 8 шт. (7 активных + 1 резерв). Электрически и программно идентичны датчикам Холла (тот же GPIO вход, логическая 1 при срабатывании). Единственный способ верификации положения механизмов |
| radio_link | Программный модуль + физический USART-передатчик для двусторонней связи с БПЛА. Протокол собственный бинарный |
| `_run_scenario_steps()` | Метод `CommandHandlers`, реализующий движок исполнения сценариев. Читает шаги из `scenarios.json`, вызывает `_dispatch_step()` для каждого. Заменяет отдельный `state_machine.py`, который не был реализован |
| NMEA 0183 | Стандартный протокол GPS. Строки $GPGGA и $GPRMC |
| LiFePO4 | Тип резервного аккумулятора: 12В. Диапазон: 10.0–13.6В. Делитель 1/11 → STM32 ADC |

---

_Минеев М.А. | ДРОНПОРТ-СПО-001 | v1.1 | 20.03.2026_

---
[[Droneport_about]]
