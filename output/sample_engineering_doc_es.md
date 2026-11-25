# Arquitectura de Telemetría de Propulsión Autónoma y Control Térmico (Esp. v2.4)

## 1. Visión General del Sistema e Ingesta Determinista

Esta especificación define el subsistema de **canalización de telemetría** en tiempo real y de **control en lazo cerrado** para la etapa de maniobra orbital (`OMS-4`). Durante las fases de encendido orbital, el bus de aviónica agrega a alta frecuencia lecturas de presión, flujo másico de propelente y temperatura de pared en un **búfer circular** de tamaño fijo antes de enviar las tramas al control en tierra. Cada trama binaria transporta una **carga útil** compacta, un contador de secuencia y una **suma de comprobación** de 32 bits validada antes de su persistencia.

Para garantizar una **tolerancia a fallos** determinista a través de enlaces espaciales intermitentes, cada transacción ascendente y descendente adjunta una **clave de idempotencia** única dentro de la cabecera `idempotency_hdr`. Los consumidores aguas abajo aplican **contrapresión** cuando las colas de ingesta superan el 80 % de capacidad y aíslan las tramas dañadas en una **cola de mensajes fallidos** tras tres ciclos fallidos de verificación.

<callout severity="critical">

Verifique el umbral `MAX_WALL_TEMP_K` en <sensor-ref id="TC-07" channel="ch0" /> antes de grabar cualquier nueva **imagen de firmware** en el controlador de propulsión.

</callout>

## 2. Física de la Protección Térmica y Eficiencia Propulsiva

La refrigeración regenerativa de la tobera previene el **embalamiento térmico** dentro del revestimiento de combustión de carburo de silicio. La transferencia térmica por conducción a través de la pared obedece la ley de Fourier, donde el **flujo de calor** local depende directamente de la **conductividad térmica** $k$ del material y del gradiente espacial de temperatura:

$$q'' = -k \nabla T$$

La eficiencia propulsiva está regida por el **impulso específico** en el vacío $I_{sp}$, definido como la razón entre el empuje $F$ y el caudal en peso de propelente $\dot{m} g_0$:

$$I_{sp} = \frac{F}{\dot{m} g_0}$$

Dado que las señales brutas de los termopares presentan ruido electromagnético durante el accionamiento de las válvulas, un **estimador de estado** de Kalman extendido ejecuta una **fusión de sensores** multitasa entre pirómetros ópticos y sondas resistivas. La matriz discreta de ganancia de Kalman $K_k$ se actualiza en cada paso de control $\Delta t \le 2\text{ ms}$:

$$K_k = P_{k|k-1} H^T \left( H P_{k|k-1} H^T + R \right)^{-1}$$

Mientras tanto, el lazo activo de modulación de válvulas reduce el **error en estado estacionario** por debajo de $\pm 0.5\text{ K}$ mediante la ley PID en tiempo continuo:

$$u(t) = K_p e(t) + K_i \int_0^t e(\tau)\,d\tau + K_d \frac{de(t)}{dt}$$

## 3. Envolvente Operativa y Matriz SLA de Telemetría

| Parámetro del Subsistema | Objetivo Nominal | Límite Superior | Variable de Telemetría |
| :--- | :--- | :--- | :--- |
| **Frecuencia de muestreo** de adquisición | $500\text{ Hz}$ | $1000\text{ Hz}$ | `sample_rate_hz` |
| **Fluctuación de retardo** temporal de extremo a extremo | $< 120\,\mu\text{s}$ | $250\,\mu\text{s}$ | `frame_jitter_us` |
| **Flujo de calor** en cámara | $4.2\text{ MW/m}^2$ | $6.8\text{ MW/m}^2$ | `wall_flux_mw_m2` |
| **Impulso específico** | $318\text{ s}$ | $326\text{ s}$ | `vac_isp_s` |
| **Error en estado estacionario** | $\le 0.25\text{ K}$ | $0.50\text{ K}$ | `thermal_ss_err_k` |

| Mecanismo de Resiliencia | Condición de Disparo | Acción de Recuperación | Símbolo de Guarda |
| :--- | :--- | :--- | :--- |
| **Interruptor de circuito** | 5 fallos CRC consecutivos | Abrir el bus y derivar a respaldo | `bus_breaker.trip()` |
| **Temporizador perro guardián** | Latido perdido $> 15\text{ ms}$ | Activar **modo a prueba de fallos** | `watchdog_kick()` |
| Recuperación tras **arranque en frío** | Reinicio por encendido o caída de tensión | Cargar **imagen de firmware** verificada | `boot_verify_crc32()` |
| **Cola de mensajes fallidos** | Presupuesto de reintentos agotado | Poner en cuarentena la **carga útil** malformada | `dlq_sink.push()` |

## 4. Seguridad de Concurrencia e Implementación del Software de Vuelo

Las tareas aviónicas multinúcleo comparten descriptores de memoria mapeados por DMA; un orden de bloqueo inadecuado puede desencadenar un **interbloqueo**, mientras que las escrituras de interrupción no sincronizadas introducen una **condición de carrera** en los contadores de secuencia de trama. En consecuencia, el software de vuelo exige indexación sin bloqueos de un solo productor y un solo consumidor dentro del **búfer circular** y valida la **suma de comprobación** de cada trama mediante `verify_crc32()`.

```python
import struct
import zlib
from collections import deque
from threading import Lock


class TelemetryRingBuffer:
    """Thread-safe circular telemetry queue with CRC32 checksum verification."""

    def __init__(self, capacity: int = 1024) -> None:
        self._buffer: deque[bytes] = deque(maxlen=capacity)
        self._lock = Lock()

    def push_frame(self, payload: bytes, expected_crc32: int) -> bool:
        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if actual_crc != expected_crc32:
            return False
        frame = struct.pack(">I", actual_crc) + payload
        with self._lock:
            self._buffer.append(frame)
        return True
```

La tarea de regulación térmica ejecuta el paso discreto de **control en lazo cerrado** a intervalos fijos de **frecuencia de muestreo**. Siempre que la temperatura de pared predicha se aproxime al límite de **embalamiento térmico**, el **interruptor de circuito** se dispara y fuerza el **modo a prueba de fallos**.

```python
class ThermalPIDController:
    """Discrete-time thermal regulator with runaway protection."""

    def __init__(self, kp: float, ki: float, kd: float, max_temp_k: float = 1150.0) -> None:
        self.kp, self.ki, self.kd = kp, ki, kd
        self.max_temp_k = max_temp_k
        self._integral = 0.0
        self._prev_error = 0.0

    def step(self, setpoint_k: float, measured_k: float, dt_s: float) -> float:
        if measured_k >= self.max_temp_k:
            return 0.0  # Immediate fail-safe cutoff
        error = setpoint_k - measured_k
        self._integral += error * dt_s
        derivative = (error - self._prev_error) / dt_s
        self._prev_error = error
        return self.kp * error + self.ki * self._integral + self.kd * derivative
```

## 5. Descriptor de Bus XML y Lista de Verificación

<telemetry-config version="2.4" bus="SpaceWire-A">
  <endpoint role="primary" idempotency="enabled" crc="CRC32-IEEE" />
  <watchdog period_ms="15" action="fail-safe-cutoff" />
  <thermal-guard max_flux_mw_m2="6.8" sensor="TC-07" />
</telemetry-config>

Antes de aprobar la aptitud para vuelo, los ingenieros deben confirmar que la inicialización de **arranque en frío** libera cualquier **contrapresión** residual en las colas, elimina los riesgos de **interbloqueo** y **condición de carrera** bajo pruebas de estrés, mantiene la **fluctuación de retardo** dentro de especificación y garantiza la **tolerancia a fallos** de extremo a extremo en la **canalización de telemetría** y el **estimador de estado** mediante **fusión de sensores** verificada.
