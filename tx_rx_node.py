import json
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Bool, String

_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

_CMD_READY = 31003  # "приготовься"
_CMD_FLY   = 31009  # "лети"
_CMD_ABORT = 31006  # "вернись в исходное"

# MAVLink system_status values
_MAV_STATE_UNINIT  = 0
_MAV_STATE_ACTIVE  = 1
_MAV_STATE_CRITICAL = 5

UINT16_MAX = 65535


class HuntUartNode(Node):
    def __init__(self) -> None:
        super().__init__('hunt_uart_node')

        self.declare_parameter('uart.device',    '/dev/ttyS1')
        self.declare_parameter('uart.baudrate',  921000)
        self.declare_parameter('fly_delay_sec',  0.5)

        device   = self.get_parameter('uart.device').value
        baudrate = self.get_parameter('uart.baudrate').value
        self._fly_delay: float = float(self.get_parameter('fly_delay_sec').value)

        self._system_status: int = _MAV_STATE_UNINIT
        self._battery: BatteryState | None = None

        self.create_subscription(String,       '/FC/status',      self._cb_fc_status, _QOS_RELIABLE)
        self.create_subscription(BatteryState, '/mavros/battery', self._cb_battery,   _QOS_RELIABLE)

        self._pub_dispatcher = self.create_publisher(String, '/dispatcher/command', _QOS_RELIABLE)
        self._pub_auto_mode  = self.create_publisher(Bool,   '/manual_drone/auto_mode', _QOS_RELIABLE)
        self._fly_timer: threading.Timer | None = None

        # Таймеры TX
        self.create_timer(1.0,  self._send_heartbeat)
        self.create_timer(0.1,  self._send_battery_status)

        # MAVLink соединение
        try:
            from pymavlink import mavutil
            self._mav = mavutil.mavlink_connection(
                device,
                baud=baudrate,
                source_system=1,
                source_component=200,
            )
            self.get_logger().info(f'Hunt UART открыт: {device} @ {baudrate}')
        except Exception as exc:
            self.get_logger().error(f'Не удалось открыть UART {device}: {exc}')
            self._mav = None
            return

        # Поток приёма команд
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

    # ── Подписки ────────────────────────────────────────────────────────────

    def _cb_fc_status(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            mode = data.get('mode', '')
            if mode in ('AUTO', 'HOLD', 'READY'):
                self._system_status = _MAV_STATE_ACTIVE
            else:
                self._system_status = _MAV_STATE_UNINIT
        except Exception:
            pass

    def _cb_battery(self, msg: BatteryState) -> None:
        self._battery = msg

    # ── TX ──────────────────────────────────────────────────────────────────

    def _send_heartbeat(self) -> None:
        if self._mav is None:
            return
        try:
            self._mav.mav.heartbeat_send(
                type=2,
                autopilot=0,
                base_mode=1,
                custom_mode=0,
                system_status=self._system_status,
            )
        except Exception as exc:
            self.get_logger().warn(f'HEARTBEAT ошибка: {exc}')

    def _send_battery_status(self) -> None:
        if self._mav is None:
            return
        bat = self._battery

        if bat is not None:
            # voltage → mV, заполняем первый элемент массива из 10
            voltage_mv = int(bat.voltage * 1000)
            voltages = [voltage_mv] + [UINT16_MAX] * 9

            current_ca       = int(bat.current * 100)        # A → cA
            battery_remaining = int(bat.percentage * 100)    # 0-1 → 0-100 %
            temperature       = int(bat.temperature) if bat.temperature > -273.0 else -1
            current_consumed  = -1   # нет накопленного значения в топике
            energy_consumed   = -1   # нет накопленного значения в топике
        else:
            voltages          = [UINT16_MAX] * 10
            current_ca        = -1
            battery_remaining = -1
            temperature       = -1
            current_consumed  = -1
            energy_consumed   = -1

        try:
            self._mav.mav.battery_status_send(
                id=0,
                battery_function=1,
                type=2,
                temperature=temperature,
                voltages=voltages,
                current_battery=current_ca,
                current_consumed=current_consumed,
                energy_consumed=energy_consumed,
                battery_remaining=battery_remaining,
            )
        except Exception as exc:
            self.get_logger().warn(f'BATTERY_STATUS ошибка: {exc}')

    def _trigger_auto_mode(self) -> None:
        msg = Bool()
        msg.data = True
        self._pub_auto_mode.publish(msg)
        self.get_logger().info('AUTO mode активирован по команде ЛЕТИ')

    # ── RX поток ────────────────────────────────────────────────────────────

    def _rx_loop(self) -> None:
        while rclpy.ok():
            try:
                msg = self._mav.recv_match(blocking=True, timeout=1.0)
                if msg is None:
                    continue
                if msg.get_type() == 'COMMAND_LONG':
                    cmd = msg.command
                    if cmd == _CMD_READY:
                        self.get_logger().info('Получена команда ПРИГОТОВЬСЯ (31003)')
                        out = String()
                        out.data = json.dumps({'type': 'READY'})
                        self._pub_dispatcher.publish(out)
                    elif cmd == _CMD_FLY:
                        self.get_logger().info('Получена команда ЛЕТИ (31009) — auto через 0.5с')
                        if self._fly_timer is not None:
                            self._fly_timer.cancel()
                        self._fly_timer = threading.Timer(self._fly_delay, self._trigger_auto_mode)
                        self._fly_timer.start()
                    elif cmd == _CMD_ABORT:
                        self.get_logger().info('Получена команда СБРОС (31006)')
                        if self._fly_timer is not None:
                            self._fly_timer.cancel()
                            self._fly_timer = None
                        auto_msg = Bool()
                        auto_msg.data = False
                        self._pub_auto_mode.publish(auto_msg)
                        out = String()
                        out.data = json.dumps({'type': 'ABORT'})
                        self._pub_dispatcher.publish(out)
                    else:
                        self.get_logger().debug(f'COMMAND_LONG command={cmd}')
            except Exception as exc:
                self.get_logger().warn(f'RX ошибка: {exc}')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = HuntUartNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
