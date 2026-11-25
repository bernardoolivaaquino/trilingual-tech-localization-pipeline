# Architecture de Télémétrie de Propulsion Autonome et de Contrôle Thermique (Spéc. v2.4)

## 1. Vue d'Ensemble du Système et Ingestion Déterministe

Cette spécification définit la **chaîne de télémétrie** temps réel et le sous-système de **commande en boucle fermée** pour l'étage de manœuvre orbitale (`OMS-4`). Pendant les phases de poussée orbitale, le bus avionique agrège à haute fréquence les mesures de pression, de débit massique d'ergols et de température de paroi dans un **tampon circulaire** de taille fixe avant d'acheminer les trames vers le contrôle au sol. Chaque trame binaire transporte une **charge utile** compacte, un compteur de séquence et une **somme de contrôle** sur 32 bits validée avant la persistance.

Pour garantir une **tolérance aux pannes** déterministe sur des liaisons spatiales intermittentes, chaque transaction montante et descendante associe une **clé d'idempotence** unique dans l'en-tête `idempotency_hdr`. Les consommateurs en aval appliquent une **contre-pression** lorsque les files d'ingestion dépassent 80 % de capacité et isolent les trames corrompues dans une **file de lettres mortes** après trois cycles de vérification infructueux.

<callout severity="critical">

Vérifiez le seuil `MAX_WALL_TEMP_K` sur <sensor-ref id="TC-07" channel="ch0" /> avant de flasher toute nouvelle **image micrologicielle** dans le contrôleur de propulsion.

</callout>

## 2. Physique de la Protection Thermique et Efficacité Propulsive

Le refroidissement régénératif de la tuyère prévient tout **emballement thermique** dans la chemise de combustion en carbure de silicium. Le transfert thermique par conduction à travers la paroi obéit à la loi de Fourier, où le **flux thermique** local dépend directement de la **conductivité thermique** $k$ du matériau et du gradient spatial de température :

$$q'' = -k \nabla T$$

L'efficacité propulsive est régie par l'**impulsion spécifique** dans le vide $I_{sp}$, définie comme le rapport entre la poussée $F$ et le débit-poids d'ergols $\dot{m} g_0$:

$$I_{sp} = \frac{F}{\dot{m} g_0}$$

Comme les signaux bruts des thermocouples présentent du bruit électromagnétique lors de l'actionnement des vannes, un **estimateur d'état** de Kalman étendu réalise une **fusion de capteurs** multicadence entre pyromètres optiques et sondes résistives. La matrice de gain de Kalman discrète $K_k$ est mise à jour à chaque pas de commande $\Delta t \le 2\text{ ms}$:

$$K_k = P_{k|k-1} H^T \left( H P_{k|k-1} H^T + R \right)^{-1}$$

Parallèlement, la boucle active de modulation des vannes maintient l'**erreur en régime permanent** en dessous de $\pm 0.5\text{ K}$ grâce à la loi PID en temps continu :

$$u(t) = K_p e(t) + K_i \int_0^t e(\tau)\,d\tau + K_d \frac{de(t)}{dt}$$

## 3. Domaine de Fonctionnement et Matrice SLA de Télémétrie

| Paramètre du Sous-Système | Cible Nominale | Borne Supérieure | Variable de Télémétrie |
| :--- | :--- | :--- | :--- |
| **Fréquence d'échantillonnage** d'acquisition | $500\text{ Hz}$ | $1000\text{ Hz}$ | `sample_rate_hz` |
| **Gigue** temporelle de bout en bout | $< 120\,\mu\text{s}$ | $250\,\mu\text{s}$ | `frame_jitter_us` |
| **Flux thermique** en chambre | $4.2\text{ MW/m}^2$ | $6.8\text{ MW/m}^2$ | `wall_flux_mw_m2` |
| **Impulsion spécifique** | $318\text{ s}$ | $326\text{ s}$ | `vac_isp_s` |
| **Erreur en régime permanent** | $\le 0.25\text{ K}$ | $0.50\text{ K}$ | `thermal_ss_err_k` |

| Mécanisme de Résilience | Condition de Déclenchement | Action de Reprise | Symbole de Garde |
| :--- | :--- | :--- | :--- |
| **Disjoncteur logiciel** | 5 échecs CRC consécutifs | Ouvrir le bus et basculer en secours | `bus_breaker.trip()` |
| **Temporisateur chien de garde** | Battement manqué $> 15\text{ ms}$ | Basculer en **mode de sécurité intégrée** | `watchdog_kick()` |
| Reprise après **démarrage à froid** | Réinitialisation à la mise sous tension ou creux de tension | Charger l'**image micrologicielle** vérifiée | `boot_verify_crc32()` |
| **File de lettres mortes** | Budget de tentatives épuisé | Mettre en quarantaine la **charge utile** malformée | `dlq_sink.push()` |

## 4. Sûreté de Concurrence et Implémentation du Logiciel de Vol

Les tâches avioniques multicœurs partagent des descripteurs mémoire mappés en DMA ; un ordre de verrouillage incorrect peut provoquer un **interblocage**, tandis que des écritures d'interruption non synchronisées introduisent une **situation de compétition** dans les compteurs de séquence. Par conséquent, le logiciel de vol impose une indexation sans verrou à producteur unique et consommateur unique dans le **tampon circulaire** et valide la **somme de contrôle** de chaque trame avec `verify_crc32()`.

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

La tâche de régulation thermique exécute le pas discret de **commande en boucle fermée** à intervalles fixes de **fréquence d'échantillonnage**. Dès que la température de paroi prédite approche du seuil d'**emballement thermique**, le **disjoncteur logiciel** se déclenche et impose le **mode de sécurité intégrée**.

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

## 5. Descripteur de Bus XML et Liste de Vérification

<telemetry-config version="2.4" bus="SpaceWire-A">
  <endpoint role="primary" idempotency="enabled" crc="CRC32-IEEE" />
  <watchdog period_ms="15" action="fail-safe-cutoff" />
  <thermal-guard max_flux_mw_m2="6.8" sensor="TC-07" />
</telemetry-config>

Avant la qualification de vol, les ingénieurs doivent confirmer que l'initialisation en **démarrage à froid** purge toute **contre-pression** résiduelle dans les files, élimine les risques d'**interblocage** et de **situation de compétition** sous test de contrainte, maintient la **gigue** dans les limites spécifiées et garantit la **tolérance aux pannes** de bout en bout sur la **chaîne de télémétrie** et l'**estimateur d'état** par une **fusion de capteurs** vérifiée.
