"""Translation backends: deterministic offline engine and production LLM adapters."""

from __future__ import annotations

import os
import re
from typing import Protocol

from src.glossary import GlossaryEngine
from src.models import CriticReport, TargetLanguage
from src.parser import TOKEN_PATTERN


class TranslationBackend(Protocol):
    """Protocol implemented by deterministic and LLM-powered translation backends."""

    def translate(
        self,
        masked_source: str,
        target_language: TargetLanguage,
        system_prompt: str,
        correction_prompt: str | None = None,
        previous_draft: str | None = None,
        critic_report: CriticReport | None = None,
    ) -> str:
        """Return a masked translation preserving all __PROTECTED_BLOCK_XX__ tokens."""


# Fluent, publication-grade line-level translations for the reference engineering spec.
_SPEC_TRANSLATIONS: dict[TargetLanguage, list[tuple[str, str]]] = {
    TargetLanguage.FR: [
        (
            "# Autonomous Propulsion Telemetry and Thermal Control Architecture (Spec v2.4)",
            "# Architecture de Télémétrie de Propulsion Autonome et de Contrôle Thermique (Spéc. v2.4)",
        ),
        (
            "## 1. System Overview and Deterministic Ingestion",
            "## 1. Vue d'Ensemble du Système et Ingestion Déterministe",
        ),
        (
            "This specification defines the real-time **telemetry pipeline** and **closed-loop control** subsystem for the Orbital Maneuvering Stage (",
            "Cette spécification définit la **chaîne de télémétrie** temps réel et le sous-système de **commande en boucle fermée** pour l'étage de manœuvre orbitale (",
        ),
        (
            "). During orbital burn phases, the avionics bus aggregates high-rate pressure, propellant mass-flow, and chamber-wall readings into a fixed-size **ring buffer** before dispatching telemetry frames to ground control. Each binary frame carries a compact **payload**, a sequence counter, and a 32-bit **checksum** validated prior to persistence.",
            "). Pendant les phases de poussée orbitale, le bus avionique agrège à haute fréquence les mesures de pression, de débit massique d'ergols et de température de paroi dans un **tampon circulaire** de taille fixe avant d'acheminer les trames vers le contrôle au sol. Chaque trame binaire transporte une **charge utile** compacte, un compteur de séquence et une **somme de contrôle** sur 32 bits validée avant la persistance.",
        ),
        (
            "To guarantee deterministic **fault tolerance** across intermittent deep-space links, every uplink and downlink transaction attaches a unique **idempotency key** inside the ",
            "Pour garantir une **tolérance aux pannes** déterministe sur des liaisons spatiales intermittentes, chaque transaction montante et descendante associe une **clé d'idempotence** unique dans l'en-tête ",
        ),
        (
            " frame header. Downstream consumers enforce **backpressure** when ingestion queues exceed 80% capacity and isolate poison frames inside a **dead-letter queue** after three failed verification cycles.",
            ". Les consommateurs en aval appliquent une **contre-pression** lorsque les files d'ingestion dépassent 80 % de capacité et isolent les trames corrompues dans une **file de lettres mortes** après trois cycles de vérification infructueux.",
        ),
        (
            "Verify the ",
            "Vérifiez le seuil ",
        ),
        (
            " threshold on ",
            " sur ",
        ),
        (
            " before flashing any new **firmware image** to the propulsion controller.",
            " avant de flasher toute nouvelle **image micrologicielle** dans le contrôleur de propulsion.",
        ),
        (
            "## 2. Physics of Thermal Protection and Propulsion Efficiency",
            "## 2. Physique de la Protection Thermique et Efficacité Propulsive",
        ),
        (
            "Regenerative nozzle cooling prevents **thermal runaway** inside the silicon-carbide combustion liner. Conductive heat transfer across the liner wall obeys Fourier's law, where the local **heat flux** depends directly on the material **thermal conductivity** ",
            "Le refroidissement régénératif de la tuyère prévient tout **emballement thermique** dans la chemise de combustion en carbure de silicium. Le transfert thermique par conduction à travers la paroi obéit à la loi de Fourier, où le **flux thermique** local dépend directement de la **conductivité thermique** ",
        ),
        (
            " and the spatial temperature gradient:",
            " du matériau et du gradient spatial de température :",
        ),
        (
            "Propulsion efficiency is governed by the vacuum **specific impulse** ",
            "L'efficacité propulsive est régie par l'**impulsion spécifique** dans le vide ",
        ),
        (
            ", defined as the ratio of thrust ",
            ", définie comme le rapport entre la poussée ",
        ),
        (
            " to propellant weight flow rate ",
            " et le débit-poids d'ergols ",
        ),
        (
            "Because raw thermocouple signals exhibit electromagnetic noise during valve actuation, an extended Kalman **state estimator** performs multi-rate **sensor fusion** between optical pyrometers and resistive probes. The discrete-time Kalman gain matrix ",
            "Comme les signaux bruts des thermocouples présentent du bruit électromagnétique lors de l'actionnement des vannes, un **estimateur d'état** de Kalman étendu réalise une **fusion de capteurs** multicadence entre pyromètres optiques et sondes résistives. La matrice de gain de Kalman discrète ",
        ),
        (
            " updates at every control step ",
            " est mise à jour à chaque pas de commande ",
        ),
        (
            "Meanwhile, the active valve-modulation loop drives the **steady-state error** below ",
            "Parallèlement, la boucle active de modulation des vannes maintient l'**erreur en régime permanent** en dessous de ",
        ),
        (
            " via the continuous-time PID law:",
            " grâce à la loi PID en temps continu :",
        ),
        (
            "## 3. Operating Envelope and Telemetry SLA Matrix",
            "## 3. Domaine de Fonctionnement et Matrice SLA de Télémétrie",
        ),
        (
            "| Subsystem Parameter | Nominal Target | Upper Bound | Telemetry Variable |",
            "| Paramètre du Sous-Système | Cible Nominale | Borne Supérieure | Variable de Télémétrie |",
        ),
        (
            "| Acquisition **sampling rate** |",
            "| **Fréquence d'échantillonnage** d'acquisition |",
        ),
        (
            "| End-to-end timing **jitter** |",
            "| **Gigue** temporelle de bout en bout |",
        ),
        (
            "| Chamber **heat flux** |",
            "| **Flux thermique** en chambre |",
        ),
        (
            "| **Specific impulse** |",
            "| **Impulsion spécifique** |",
        ),
        (
            "| **Steady-state error** |",
            "| **Erreur en régime permanent** |",
        ),
        (
            "| Resilience Mechanism | Trigger Condition | Recovery Action | Guard Symbol |",
            "| Mécanisme de Résilience | Condition de Déclenchement | Action de Reprise | Symbole de Garde |",
        ),
        (
            "| **Circuit breaker** | 5 consecutive CRC failures | Open bus & route to fallback |",
            "| **Disjoncteur logiciel** | 5 échecs CRC consécutifs | Ouvrir le bus et basculer en secours |",
        ),
        (
            "| **Watchdog timer** | Missed heartbeat ",
            "| **Temporisateur chien de garde** | Battement manqué ",
        ),
        (
            " | Enter **fail-safe mode** |",
            " | Basculer en **mode de sécurité intégrée** |",
        ),
        (
            "| **Cold start** recovery | Power-on reset or brownout | Load verified **firmware image** |",
            "| Reprise après **démarrage à froid** | Réinitialisation à la mise sous tension ou creux de tension | Charger l'**image micrologicielle** vérifiée |",
        ),
        (
            "| **Dead-letter queue** | Exhausted retry budget | Quarantine malformed **payload** |",
            "| **File de lettres mortes** | Budget de tentatives épuisé | Mettre en quarantaine la **charge utile** malformée |",
        ),
        (
            "## 4. Concurrency Safety and Flight Software Implementation",
            "## 4. Sûreté de Concurrence et Implémentation du Logiciel de Vol",
        ),
        (
            "Multi-core avionics tasks share DMA-mapped memory descriptors; improper lock ordering can trigger a **deadlock**, while unsynchronized ISR writes introduce a **race condition** in frame sequence counters. Consequently, the flight software mandates lock-free single-producer/single-consumer indexing inside the **ring buffer** and validates every frame **checksum** using ",
            "Les tâches avioniques multicœurs partagent des descripteurs mémoire mappés en DMA ; un ordre de verrouillage incorrect peut provoquer un **interblocage**, tandis que des écritures d'interruption non synchronisées introduisent une **situation de compétition** dans les compteurs de séquence. Par conséquent, le logiciel de vol impose une indexation sans verrou à producteur unique et consommateur unique dans le **tampon circulaire** et valide la **somme de contrôle** de chaque trame avec ",
        ),
        (
            "The thermal regulation task executes the discrete **closed-loop control** step at fixed **sampling rate** intervals. Whenever predicted wall temperature approaches the **thermal runaway** boundary, the **circuit breaker** trips and forces **fail-safe mode**.",
            "La tâche de régulation thermique exécute le pas discret de **commande en boucle fermée** à intervalles fixes de **fréquence d'échantillonnage**. Dès que la température de paroi prédite approche du seuil d'**emballement thermique**, le **disjoncteur logiciel** se déclenche et impose le **mode de sécurité intégrée**.",
        ),
        (
            "## 5. XML Bus Descriptor and Verification Checklist",
            "## 5. Descripteur de Bus XML et Liste de Vérification",
        ),
        (
            "Before flight-readiness sign-off, engineers must confirm that **cold start** initialization clears residual queue **backpressure**, eliminates **deadlock** and **race condition** hazards under stress testing, keeps **jitter** within spec, and guarantees end-to-end **fault tolerance** across the **telemetry pipeline** and **state estimator** via verified **sensor fusion**.",
            "Avant la qualification de vol, les ingénieurs doivent confirmer que l'initialisation en **démarrage à froid** purge toute **contre-pression** résiduelle dans les files, élimine les risques d'**interblocage** et de **situation de compétition** sous test de contrainte, maintient la **gigue** dans les limites spécifiées et garantit la **tolérance aux pannes** de bout en bout sur la **chaîne de télémétrie** et l'**estimateur d'état** par une **fusion de capteurs** vérifiée.",
        ),
    ],
    TargetLanguage.ES: [
        (
            "# Autonomous Propulsion Telemetry and Thermal Control Architecture (Spec v2.4)",
            "# Arquitectura de Telemetría de Propulsión Autónoma y Control Térmico (Esp. v2.4)",
        ),
        (
            "## 1. System Overview and Deterministic Ingestion",
            "## 1. Visión General del Sistema e Ingesta Determinista",
        ),
        (
            "This specification defines the real-time **telemetry pipeline** and **closed-loop control** subsystem for the Orbital Maneuvering Stage (",
            "Esta especificación define el subsistema de **canalización de telemetría** en tiempo real y de **control en lazo cerrado** para la etapa de maniobra orbital (",
        ),
        (
            "). During orbital burn phases, the avionics bus aggregates high-rate pressure, propellant mass-flow, and chamber-wall readings into a fixed-size **ring buffer** before dispatching telemetry frames to ground control. Each binary frame carries a compact **payload**, a sequence counter, and a 32-bit **checksum** validated prior to persistence.",
            "). Durante las fases de encendido orbital, el bus de aviónica agrega a alta frecuencia lecturas de presión, flujo másico de propelente y temperatura de pared en un **búfer circular** de tamaño fijo antes de enviar las tramas al control en tierra. Cada trama binaria transporta una **carga útil** compacta, un contador de secuencia y una **suma de comprobación** de 32 bits validada antes de su persistencia.",
        ),
        (
            "To guarantee deterministic **fault tolerance** across intermittent deep-space links, every uplink and downlink transaction attaches a unique **idempotency key** inside the ",
            "Para garantizar una **tolerancia a fallos** determinista a través de enlaces espaciales intermitentes, cada transacción ascendente y descendente adjunta una **clave de idempotencia** única dentro de la cabecera ",
        ),
        (
            " frame header. Downstream consumers enforce **backpressure** when ingestion queues exceed 80% capacity and isolate poison frames inside a **dead-letter queue** after three failed verification cycles.",
            ". Los consumidores aguas abajo aplican **contrapresión** cuando las colas de ingesta superan el 80 % de capacidad y aíslan las tramas dañadas en una **cola de mensajes fallidos** tras tres ciclos fallidos de verificación.",
        ),
        (
            "Verify the ",
            "Verifique el umbral ",
        ),
        (
            " threshold on ",
            " en ",
        ),
        (
            " before flashing any new **firmware image** to the propulsion controller.",
            " antes de grabar cualquier nueva **imagen de firmware** en el controlador de propulsión.",
        ),
        (
            "## 2. Physics of Thermal Protection and Propulsion Efficiency",
            "## 2. Física de la Protección Térmica y Eficiencia Propulsiva",
        ),
        (
            "Regenerative nozzle cooling prevents **thermal runaway** inside the silicon-carbide combustion liner. Conductive heat transfer across the liner wall obeys Fourier's law, where the local **heat flux** depends directly on the material **thermal conductivity** ",
            "La refrigeración regenerativa de la tobera previene el **embalamiento térmico** dentro del revestimiento de combustión de carburo de silicio. La transferencia térmica por conducción a través de la pared obedece la ley de Fourier, donde el **flujo de calor** local depende directamente de la **conductividad térmica** ",
        ),
        (
            " and the spatial temperature gradient:",
            " del material y del gradiente espacial de temperatura:",
        ),
        (
            "Propulsion efficiency is governed by the vacuum **specific impulse** ",
            "La eficiencia propulsiva está regida por el **impulso específico** en el vacío ",
        ),
        (
            ", defined as the ratio of thrust ",
            ", definido como la razón entre el empuje ",
        ),
        (
            " to propellant weight flow rate ",
            " y el caudal en peso de propelente ",
        ),
        (
            "Because raw thermocouple signals exhibit electromagnetic noise during valve actuation, an extended Kalman **state estimator** performs multi-rate **sensor fusion** between optical pyrometers and resistive probes. The discrete-time Kalman gain matrix ",
            "Dado que las señales brutas de los termopares presentan ruido electromagnético durante el accionamiento de las válvulas, un **estimador de estado** de Kalman extendido ejecuta una **fusión de sensores** multitasa entre pirómetros ópticos y sondas resistivas. La matriz discreta de ganancia de Kalman ",
        ),
        (
            " updates at every control step ",
            " se actualiza en cada paso de control ",
        ),
        (
            "Meanwhile, the active valve-modulation loop drives the **steady-state error** below ",
            "Mientras tanto, el lazo activo de modulación de válvulas reduce el **error en estado estacionario** por debajo de ",
        ),
        (
            " via the continuous-time PID law:",
            " mediante la ley PID en tiempo continuo:",
        ),
        (
            "## 3. Operating Envelope and Telemetry SLA Matrix",
            "## 3. Envolvente Operativa y Matriz SLA de Telemetría",
        ),
        (
            "| Subsystem Parameter | Nominal Target | Upper Bound | Telemetry Variable |",
            "| Parámetro del Subsistema | Objetivo Nominal | Límite Superior | Variable de Telemetría |",
        ),
        (
            "| Acquisition **sampling rate** |",
            "| **Frecuencia de muestreo** de adquisición |",
        ),
        (
            "| End-to-end timing **jitter** |",
            "| **Fluctuación de retardo** temporal de extremo a extremo |",
        ),
        (
            "| Chamber **heat flux** |",
            "| **Flujo de calor** en cámara |",
        ),
        (
            "| **Specific impulse** |",
            "| **Impulso específico** |",
        ),
        (
            "| **Steady-state error** |",
            "| **Error en estado estacionario** |",
        ),
        (
            "| Resilience Mechanism | Trigger Condition | Recovery Action | Guard Symbol |",
            "| Mecanismo de Resiliencia | Condición de Disparo | Acción de Recuperación | Símbolo de Guarda |",
        ),
        (
            "| **Circuit breaker** | 5 consecutive CRC failures | Open bus & route to fallback |",
            "| **Interruptor de circuito** | 5 fallos CRC consecutivos | Abrir el bus y derivar a respaldo |",
        ),
        (
            "| **Watchdog timer** | Missed heartbeat ",
            "| **Temporizador perro guardián** | Latido perdido ",
        ),
        (
            " | Enter **fail-safe mode** |",
            " | Activar **modo a prueba de fallos** |",
        ),
        (
            "| **Cold start** recovery | Power-on reset or brownout | Load verified **firmware image** |",
            "| Recuperación tras **arranque en frío** | Reinicio por encendido o caída de tensión | Cargar **imagen de firmware** verificada |",
        ),
        (
            "| **Dead-letter queue** | Exhausted retry budget | Quarantine malformed **payload** |",
            "| **Cola de mensajes fallidos** | Presupuesto de reintentos agotado | Poner en cuarentena la **carga útil** malformada |",
        ),
        (
            "## 4. Concurrency Safety and Flight Software Implementation",
            "## 4. Seguridad de Concurrencia e Implementación del Software de Vuelo",
        ),
        (
            "Multi-core avionics tasks share DMA-mapped memory descriptors; improper lock ordering can trigger a **deadlock**, while unsynchronized ISR writes introduce a **race condition** in frame sequence counters. Consequently, the flight software mandates lock-free single-producer/single-consumer indexing inside the **ring buffer** and validates every frame **checksum** using ",
            "Las tareas aviónicas multinúcleo comparten descriptores de memoria mapeados por DMA; un orden de bloqueo inadecuado puede desencadenar un **interbloqueo**, mientras que las escrituras de interrupción no sincronizadas introducen una **condición de carrera** en los contadores de secuencia de trama. En consecuencia, el software de vuelo exige indexación sin bloqueos de un solo productor y un solo consumidor dentro del **búfer circular** y valida la **suma de comprobación** de cada trama mediante ",
        ),
        (
            "The thermal regulation task executes the discrete **closed-loop control** step at fixed **sampling rate** intervals. Whenever predicted wall temperature approaches the **thermal runaway** boundary, the **circuit breaker** trips and forces **fail-safe mode**.",
            "La tarea de regulación térmica ejecuta el paso discreto de **control en lazo cerrado** a intervalos fijos de **frecuencia de muestreo**. Siempre que la temperatura de pared predicha se aproxime al límite de **embalamiento térmico**, el **interruptor de circuito** se dispara y fuerza el **modo a prueba de fallos**.",
        ),
        (
            "## 5. XML Bus Descriptor and Verification Checklist",
            "## 5. Descriptor de Bus XML y Lista de Verificación",
        ),
        (
            "Before flight-readiness sign-off, engineers must confirm that **cold start** initialization clears residual queue **backpressure**, eliminates **deadlock** and **race condition** hazards under stress testing, keeps **jitter** within spec, and guarantees end-to-end **fault tolerance** across the **telemetry pipeline** and **state estimator** via verified **sensor fusion**.",
            "Antes de aprobar la aptitud para vuelo, los ingenieros deben confirmar que la inicialización de **arranque en frío** libera cualquier **contrapresión** residual en las colas, elimina los riesgos de **interbloqueo** y **condición de carrera** bajo pruebas de estrés, mantiene la **fluctuación de retardo** dentro de especificación y garantiza la **tolerancia a fallos** de extremo a extremo en la **canalización de telemetría** y el **estimador de estado** mediante **fusión de sensores** verificada.",
        ),
    ],
}

# Realistic generic-MT drift substitutions simulated on pass 1 before TerminologyCriticAgent audit.
_DRIFT_TERM_IDS_FORBIDDEN = [
    "TERM-002",  # thermal runaway -> fuite thermique / fuga térmica
    "TERM-004",  # circuit breaker -> casseur de circuit / rompedor de circuito
    "TERM-005",  # dead-letter queue -> queue de lettres décédées / cola de cartas muertas
    "TERM-006",  # backpressure -> pression arrière / presión trasera
    "TERM-009",  # watchdog timer -> minuterie de chien / reloj vigilante
    "TERM-010",  # ring buffer -> tampon d'anneau / búfer de anillo
    "TERM-011",  # deadlock -> serrure morte / cerradura muerta
    "TERM-012",  # race condition -> condition de course / condición de raza
    "TERM-021",  # jitter -> tremblement / temblor
]
_DRIFT_TERM_IDS_UNTRANSLATED = [
    "TERM-008",  # cold start left in English
    "TERM-025",  # checksum left in English
]

_GENERIC_PHRASES: dict[TargetLanguage, list[tuple[str, str]]] = {
    TargetLanguage.FR: [
        ("This module implements", "Ce module implémente"),
        ("Configure the", "Configurez le"),
        ("Ensure that", "Assurez-vous que"),
        ("System Architecture", "Architecture du Système"),
        ("Overview", "Vue d'ensemble"),
        ("before", "avant"),
        ("under", "sous"),
        ("with", "avec"),
        ("and", "et"),
        ("the", "le"),
    ],
    TargetLanguage.ES: [
        ("This module implements", "Este módulo implementa"),
        ("Configure the", "Configurar el"),
        ("Ensure that", "Asegúrese de que"),
        ("System Architecture", "Arquitectura del Sistema"),
        ("Overview", "Resumen General"),
        ("before", "antes de"),
        ("under", "bajo"),
        ("with", "con"),
        ("and", "y"),
        ("the", "el"),
    ],
}


class DeterministicLocalizationBackend:
    """Reproducible offline translation backend with optional drift & critic-repair cycle."""

    def __init__(
        self,
        glossary_engine: GlossaryEngine,
        simulate_initial_drift: bool = False,
    ) -> None:
        self.glossary_engine = glossary_engine
        self.simulate_initial_drift = simulate_initial_drift

    def translate(
        self,
        masked_source: str,
        target_language: TargetLanguage,
        system_prompt: str,
        correction_prompt: str | None = None,
        previous_draft: str | None = None,
        critic_report: CriticReport | None = None,
    ) -> str:
        """Translate masked Markdown cleanly, or repair a flagged draft using critic feedback."""
        if correction_prompt is not None and previous_draft is not None and critic_report is not None:
            return self._apply_critic_repairs(
                masked_source=masked_source,
                previous_draft=previous_draft,
                critic_report=critic_report,
                target_language=target_language,
            )

        translated = self._produce_compliant_translation(masked_source, target_language)

        if self.simulate_initial_drift and correction_prompt is None:
            translated = self._inject_realistic_drift(translated, target_language)

        return translated

    def _produce_compliant_translation(
        self,
        masked_source: str,
        target_language: TargetLanguage,
    ) -> str:
        out = masked_source
        # Apply fluent specification translations (ordered longest-first to avoid partial clashes).
        pairs = sorted(
            _SPEC_TRANSLATIONS[target_language],
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for src_frag, tgt_frag in pairs:
            out = out.replace(src_frag, tgt_frag)

        # Translate any remaining glossary terms outside protected tokens (handles arbitrary inputs).
        out = self._translate_glossary_terms_outside_tokens(out, target_language)

        # For non-spec snippets, lightly translate common English structural phrases outside tokens.
        if out == masked_source or any(
            phrase in out for phrase, _ in _GENERIC_PHRASES[target_language][:5]
        ):
            out = self._replace_outside_tokens(out, _GENERIC_PHRASES[target_language])

        return out

    def _translate_glossary_terms_outside_tokens(
        self,
        text: str,
        target_language: TargetLanguage,
    ) -> str:
        # Sort longest English terms first so multi-word phrases win over substrings.
        sorted_terms = sorted(
            self.glossary_engine.glossary.terms,
            key=lambda t: len(t.en),
            reverse=True,
        )
        replacements: list[tuple[re.Pattern[str], str]] = []
        for term in sorted_terms:
            target = term.target_term(target_language)
            for candidate in [term.en, *term.en_aliases]:
                pat = re.compile(
                    rf"(?<![A-Za-z0-9_]){re.escape(candidate)}(?![A-Za-z0-9_])",
                    re.IGNORECASE,
                )
                replacements.append((pat, target))

        return self._apply_regex_outside_tokens(text, replacements)

    def _inject_realistic_drift(
        self,
        compliant_text: str,
        target_language: TargetLanguage,
    ) -> str:
        term_by_id = {t.id: t for t in self.glossary_engine.glossary.terms}
        replacements: list[tuple[re.Pattern[str], str]] = []

        for tid in _DRIFT_TERM_IDS_FORBIDDEN:
            term = term_by_id.get(tid)
            if not term:
                continue
            target = term.target_term(target_language)
            forbidden = term.forbidden_terms(target_language)
            if forbidden:
                pat = re.compile(re.escape(target), re.IGNORECASE)
                replacements.append((pat, forbidden[0]))

        for tid in _DRIFT_TERM_IDS_UNTRANSLATED:
            term = term_by_id.get(tid)
            if not term:
                continue
            target = term.target_term(target_language)
            pat = re.compile(re.escape(target), re.IGNORECASE)
            replacements.append((pat, term.en))

        return self._apply_regex_outside_tokens(compliant_text, replacements)

    def _apply_critic_repairs(
        self,
        masked_source: str,
        previous_draft: str,
        critic_report: CriticReport,
        target_language: TargetLanguage,
    ) -> str:
        repaired = previous_draft
        term_by_id = {t.id: t for t in self.glossary_engine.glossary.terms}
        replacements: list[tuple[re.Pattern[str], str]] = []

        for obs in critic_report.observations:
            if obs.code in ("FORBIDDEN_TERM_USED", "UNTRANSLATED_TERM") and obs.found and obs.expected:
                pat = re.compile(re.escape(obs.found), re.IGNORECASE)
                replacements.append((pat, obs.expected))
            elif obs.code == "MANDATORY_TERM_MISSING" and obs.term_id and obs.expected:
                term = term_by_id.get(obs.term_id)
                if term:
                    for candidate in [term.en, *term.en_aliases, *term.forbidden_terms(target_language)]:
                        pat = re.compile(re.escape(candidate), re.IGNORECASE)
                        replacements.append((pat, obs.expected))

        repaired = self._apply_regex_outside_tokens(repaired, replacements)

        # If any protected tokens were lost or duplicated, fall back to a clean compliant pass.
        if critic_report.token_integrity_rate < 100.0:
            repaired = self._produce_compliant_translation(masked_source, target_language)

        return repaired

    @staticmethod
    def _replace_outside_tokens(text: str, pairs: list[tuple[str, str]]) -> str:
        replacements = [
            (re.compile(rf"\b{re.escape(src)}\b"), tgt) for src, tgt in pairs
        ]
        return DeterministicLocalizationBackend._apply_regex_outside_tokens(text, replacements)

    @staticmethod
    def _apply_regex_outside_tokens(
        text: str,
        replacements: list[tuple[re.Pattern[str], str]],
    ) -> str:
        parts: list[str] = []
        cursor = 0
        for match in TOKEN_PATTERN.finditer(text):
            chunk = text[cursor : match.start()]
            for pat, repl in replacements:
                chunk = pat.sub(lambda m, r=repl: _match_case(m.group(0), r), chunk)
            parts.append(chunk)
            parts.append(match.group(0))
            cursor = match.end()

        tail = text[cursor:]
        for pat, repl in replacements:
            tail = pat.sub(lambda m, r=repl: _match_case(m.group(0), r), tail)
        parts.append(tail)
        return "".join(parts)


def _match_case(source_span: str, replacement: str) -> str:
    """Preserve initial capitalization when replacing a matched term."""
    if not source_span or not replacement:
        return replacement
    if source_span[0].isupper() and replacement[0].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


class OpenAIBackend:
    """OpenAI Chat Completions backend for production LLM translation."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def translate(
        self,
        masked_source: str,
        target_language: TargetLanguage,
        system_prompt: str,
        correction_prompt: str | None = None,
        previous_draft: str | None = None,
        critic_report: CriticReport | None = None,
    ) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is required for OpenAIBackend.")
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Translate the following masked Markdown into {target_language.value}:\n\n{masked_source}"},
        ]
        if correction_prompt and previous_draft:
            messages.append({"role": "assistant", "content": previous_draft})
            messages.append({"role": "user", "content": correction_prompt})

        response = client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=messages,  # type: ignore[arg-type]
        )
        return (response.choices[0].message.content or "").strip()


class GeminiBackend:
    """Google GenAI backend for production LLM translation."""

    def __init__(self, model: str = "gemini-2.5-flash") -> None:
        self.model = model

    def translate(
        self,
        masked_source: str,
        target_language: TargetLanguage,
        system_prompt: str,
        correction_prompt: str | None = None,
        previous_draft: str | None = None,
        critic_report: CriticReport | None = None,
    ) -> str:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is required for GeminiBackend.")
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = f"Translate the following masked Markdown into {target_language.value}:\n\n{masked_source}"
        if correction_prompt and previous_draft:
            prompt += f"\n\nPrevious draft:\n{previous_draft}\n\n{correction_prompt}"

        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
            ),
        )
        return (response.text or "").strip()


class AnthropicBackend:
    """Anthropic Messages backend for production LLM translation."""

    def __init__(self, model: str = "claude-3-5-sonnet-latest") -> None:
        self.model = model

    def translate(
        self,
        masked_source: str,
        target_language: TargetLanguage,
        system_prompt: str,
        correction_prompt: str | None = None,
        previous_draft: str | None = None,
        critic_report: CriticReport | None = None,
    ) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is required for AnthropicBackend.")
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        messages: list[dict[str, str]] = [
            {"role": "user", "content": f"Translate the following masked Markdown into {target_language.value}:\n\n{masked_source}"},
        ]
        if correction_prompt and previous_draft:
            messages.append({"role": "assistant", "content": previous_draft})
            messages.append({"role": "user", "content": correction_prompt})

        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.1,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
        )
        return "".join(block.text for block in response.content if hasattr(block, "text")).strip()


def create_backend(
    name: str,
    glossary_engine: GlossaryEngine,
    simulate_initial_drift: bool = False,
) -> TranslationBackend:
    """Factory creating a translation backend by provider name."""
    normalized = name.strip().lower()
    if normalized == "deterministic":
        return DeterministicLocalizationBackend(
            glossary_engine=glossary_engine,
            simulate_initial_drift=simulate_initial_drift,
        )
    if normalized == "openai":
        return OpenAIBackend()
    if normalized == "gemini":
        return GeminiBackend()
    if normalized == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"Unsupported translation backend: {name!r}")
