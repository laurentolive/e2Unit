# e2Unit

Framework de test unitaire de fonctions C, **sur PC et sur cible**, avec le même fichier de test.

- Les tests sont **déclarés** (YAML) : prototype C de la fonction, stimuli, résultat attendu, tolérance.
- Le code d'interface C (adapters) est **généré** depuis le prototype : rien à écrire pour une fonction "scalaire".
- La même suite s'exécute :
  - `host` : bibliothèque partagée (gcc PC) appelée par ctypes — rapide, pour le développement et la CI ;
  - `sim`  : même bibliothèque, mais pilotée par le **protocole cible** (mailbox) — valide le protocole sans matériel ;
  - `emu`  : **le firmware ARM réel** (arm-none-eabi-gcc) exécuté dans un émulateur Cortex-M (Unicorn) ;
  - `jlink`: le firmware sur la carte, piloté par la sonde J-Link en SWD, avec mesure des cycles CPU.
- Sur cible, chaque sortie peut être comparée **bit à bit** au résultat PC (`--compare-host`) : détection
  automatique des écarts de compilateur, d'optimisation ou de taille de type.
- Rapports : console, JUnit XML (Jenkins), JSON, Excel (traçabilité exigence → test → vérification), graphes PNG.

## Arborescence

```
eunit/                 package Python (orchestrateur)
  spec.py              chargement / validation des suites
  codegen.py           génération eunit_suite.c + suite.mk
  stimuli.py           générateurs de stimuli
  checks.py            vérifications (tolérance, bornes, cycles, comparaison)
  engine.py            exécution
  runners/             host, sim, emu (Unicorn), jlink (pylink) + protocole mailbox
  report.py, plot.py   rapports
  mcp_server.py        serveur MCP (assistants IA)
target/                runtime C embarqué
  include/eunit.h      API, ABI des adapters, structure de la mailbox
  src/eunit_runtime.c  exécution par lots + serveur mailbox
  port/host/           portage PC (bibliothèque partagée + cible simulée)
  port/cortex-m/       portage Cortex-M (DWT/SysTick, startup minimal, main, sections)
boards/ra4e1/          carte : options CPU, script de link, nom J-Link
mk/eunit.mk            règles make communes
examples/emath/        exemple : sin, atan2, pow, isqrt, rms en virgule fixe
selftest/              autotests du framework (dont fonctions volontairement fausses)
docs/                  tutoriels FR (tutoriels/) et EN (tutorials/), images (img/)
eunit_cli.py           point d'entrée (python eunit_cli.py --help)
```

## Prérequis

- Python 3.10+ avec `numpy`, `pyyaml` ; optionnels : `openpyxl` (Excel), `matplotlib` (graphes),
  `pyelftools` + `pylink-square` (J-Link), `unicorn` (émulateur).
- GNU make, gcc PC (ex. MSYS2 ucrt64), arm-none-eabi-gcc, J-Link Software.
- Copier `eunit.local.mk.example` en `eunit.local.mk` et y mettre les chemins des outils.

## Démarrage rapide

```
cd examples/emath
make test            # toutes les suites sur PC
make test-sim        # via le protocole mailbox (sans matériel)
make target          # un firmware par suite + le firmware global (tests/all)
make test-emu        # firmware ARM dans l'émulateur, comparé au PC
make test-target     # flash + exécution sur carte J-Link, comparé au PC
make test/sin        # une seule suite
```

Dans le répertoire d'une suite (`examples/emath/tests/sin`) : `make`, `make test-emu`, `make flash`,
`make list`, `make clean`. Options : `make EUNIT_RUN_OPTS="-v --plot build/plots"`,
`make test-target JLINK_OPTS="--serial 123456 --speed 12000"`, `make BOARD=...`.

Le code retour est le verdict : 0 = PASS, 1 = FAIL, 2 = erreur (spécification, build, sonde).

## Écrire une suite

Une suite = un fichier YAML + un Makefile de 3 lignes :

```make
EUNIT_ROOT := ../../../..
SUITE      := sin.yaml
include $(EUNIT_ROOT)/mk/eunit.mk
```

```yaml
suite: sin
build:
  sources: [../../src/emath_sin.c]     # chemins relatifs au fichier YAML
  includes: [../../src]
  headers: [emath.h]                   # inclus dans le code généré
  defines: []
models: [../emath_ref.py]              # fonctions Python utilisables dans les expressions

functions:
  sin:
    prototype: "int16_t emath_sin(int16_t angle)"
    returns: y                         # nom de la sortie (défaut : ret)

tests:
  - id: SIN-001
    title: accuracy over the full turn
    requirement: EMATH-SIN-01          # ou une liste
    call: sin
    stimuli:
      angle: {range: [-32768, 32767]}
    checks:
      - desc: "|y - ideal| <= 2 LSB"
        expect: sin_q15(angle)         # expression numpy (entrées, sorties, i, n, modèles)
        tolerance: {abs: 2}
      - cycles: {max: 200}             # cible J-Link uniquement, SKIP ailleurs
```

### Fonctions

- `prototype` : prototype C. Types : `int8_t … uint32_t`, `bool`, `float` (et alias `u8`, `s16`, `f32`, …).
  Le prototype est redéclaré dans le code généré : un écart avec l'en-tête est une **erreur de compilation**.
- Une fonction avec pointeurs, contexte ou plusieurs sorties utilise un **adapter manuel** :
  `custom: true` (+ `outputs: "uint32_t acc, int16_t last"` pour des sorties supplémentaires), puis en C :

  ```c
  #include "eunit.h"
  static emath_rms_t ctx;
  EUNIT_ADAPTER(rms_update) { out[0] = (int32_t)emath_rms_update(&ctx, (int16_t)in[0]); }
  ```

  Pour tester une fonction `static`, l'adapter peut faire `#include "module.c"`.

### Stimuli

| Forme | Exemple |
|---|---|
| constante | `k: 0.5` |
| valeurs | `x: [0, 16384, -32768]` |
| plage entière (bornes incluses) | `{range: [-32768, 32767], step: 1}` |
| linspace | `{linspace: [-32768, 32767, 257]}` |
| aléatoire (déterministe) | `{random: [0, 4294967295], n: 200000, seed: 1}` |
| signal par segments | `{segments: [{n: 300, dc: 0}, {n: 600, sine: {amp: 20000, period: 64}}, {n: 100, ramp: [0, 1000], noise: 50}]}` |
| expression de l'index `i` | `{expr: "(i // 3 + 1) ** 2 + i % 3 - 1", n: 196605}` |
| fichier | `{file: data.npy}` ou `.csv` |

Entrées combinées par `combine: zip` (défaut, même longueur, constantes diffusées) ou `combine: grid`
(produit cartésien). Une valeur hors de la plage du type C est une **erreur** (jamais tronquée en silence).

### Vérifications

- `expect` (+ `tolerance: {abs, rel, modulo}`) : valeur attendue, expression ou liste.
  `modulo: 65536` compare des angles binaires modulo un tour.
- `min` / `max` : bornes.
- `cycles: {max, mean}` : temps d'exécution (cible).
- `window: [début, fin]` (indices Python, `null` = bout) et `where: "<expression booléenne>"` restreignent les échantillons.
- Helpers disponibles : `np`, `sat(x, 'int16_t')`, `wrap(x, 'uint8_t')`, `isqrt`, `shift(x, k)`, fonctions de `models`.

### État, setup, reset

Avant chaque test, le runner remet le code à son état initial (rechargement de la bibliothèque sur PC,
reset de la cible) : les variables statiques repartent de zéro. `reset: false` enchaîne sur l'état
du test précédent. `setup:` appelle des fonctions avant les stimuli, ex. `setup: [{rms_init: [6]}]`.

### Suite globale

`include: [../sin/sin.yaml, ../rms/rms.yaml]` fusionne sources, fonctions et tests : un seul
firmware de test pour toutes les fonctions (`examples/emath/tests/all`). Sinon, un firmware par suite.

## Sur cible

### Firmware de test autonome

`make target` produit `build/<board>/<suite>.elf/.hex/.map` : startup minimal + runtime + fonctions
testées, sans interruption ni périphérique. `make flash` le programme, `make test-target` le flashe,
l'exécute et compare au PC. Une faute CPU (HardFault) ou une fonction bloquée est rapportée (ERROR)
avec le PC fautif, puis la cible est réinitialisée pour le test suivant.

Nouvelle carte : `boards/<nom>/board.mk` (`BOARD_CPU_FLAGS`, `BOARD_LDSCRIPT`, `BOARD_DEFS`,
`JLINK_DEVICE`, `BOARD_EMU_CPU`) + script de link (MEMORY puis `INCLUDE eunit_sections.ld`).
Les cœurs sans DWT (M0/M0+/M23) utilisent SysTick pour les cycles.

### Intégration dans une application existante (ex. projet FSP)

Ajouter au projet `target/src/eunit_runtime.c`, `target/port/cortex-m/eunit_port_cortexm.c`,
`build/gen/eunit_suite.c` (généré par `python eunit_cli.py gen suite.yaml --out build/gen`), puis :

```c
eunit_init();
for (;;) { eunit_poll(); /* ... */ }
```

et lancer `python eunit_cli.py run suite.yaml --runner jlink --elf app.elf --device R7FA4E10D`.
Optionnellement, définir `HardFault_Handler` pour appeler `eunit_fault(pc)`.

### Protocole

La mailbox `eunit_mailbox` (adresse lue dans l'ELF) contient un en-tête de mots 32 bits
(magic, version, hash de la suite, taille du buffer, `req`/`ack`, commande, statistiques de cycles)
suivi du buffer d'échange. L'hôte écrit les entrées et `req = seq + 1` ; la cible exécute le lot,
écrit les sorties puis `ack = req`. Les lots sont découpés selon la taille du buffer (`EUNIT_BUF_WORDS`).
Le hash garantit que le firmware correspond à la spécification (sinon : erreur "rebuild it").

## Serveur MCP (assistants IA)

`python eunit_cli.py mcp` lance un serveur [MCP](https://modelcontextprotocol.io) sur stdio, sans
dépendance supplémentaire. Un assistant (Claude Code, Claude Desktop, VS Code...) peut alors :

| Outil | Rôle |
|---|---|
| `find_suites` | trouver les suites YAML sous un répertoire |
| `describe_suite` | charger et valider une suite : fonctions, tests, exigences, vérifications, hash |
| `build` | `make host`, `target`, les deux, ou `clean` ; renvoie la sortie du compilateur |
| `run_suite` | compiler et exécuter sur `host`, `sim`, `emu` ou `target` (J-Link), filtre `tests`, graphes ; renvoie le verdict et le détail de chaque test (`results.json`) |
| `add_test`, `get_test`, `update_test`, `remove_test` | écrire les tests d'une suite (ou du fichier inclus qui les définit) |
| `add_function` | déclarer une fonction à tester, avec ses sources, includes et en-têtes |
| `create_suite` | créer `<nom>.yaml` + `Makefile` d'une nouvelle suite, avec ses premiers tests |
| `list_probes`, `license_status` | sondes J-Link connectées, licence du poste |

Les modifications gardent le reste du fichier tel quel (commentaires, mise en page) et sont
validées avant d'être écrites : chargement de la suite et des suites qui incluent le fichier,
génération des stimuli du test. Une modification refusée laisse le fichier intact. `dry_run: true`
renvoie le YAML produit sans rien écrire.

Le README et les tutoriels sont exposés comme ressources (`eunit://docs/...`). Les builds et les
exécutions passent par make et la CLI dans des processus fils, comme depuis un terminal : les
rapports restent dans `build/report`. Les chemins relatifs partent du répertoire de travail du serveur.

Dans ce dépôt, `.mcp.json` déclare le serveur pour Claude Code. Ailleurs :

```
claude mcp add e2unit -e EUNIT_MAKE=C:/Dev/Tools/make.exe -- python C:/chemin/e2Unit/eunit_cli.py mcp
```

`make` doit être dans le `PATH`, ou donné par la variable `EUNIT_MAKE`. Si aucune licence n'est encore
choisie, la fenêtre de licence apparaît au premier `run_suite` (en CI : `EUNIT_LICENSE_KEY`).

## Autotests du framework

```
EUNIT_MAKE=C:/Dev/Tools/make.exe python -m unittest discover -s selftest -v
```

Le fixture `selftest/fixture` contient des fonctions correctes et fausses : chaque test y documente
le verdict attendu (PASS / FAIL / ERROR), y compris blocage, faute CPU et reprise sur l'émulateur.

## Licence

L'outil PC (package `eunit/`, makefiles) est en source disponible sous
[PolyForm Noncommercial 1.0.0](LICENSE.md), même modèle qu'eScope :

- **Personnelle** (gratuite) : projets personnels, études, recherche, enseignement ;
- **Démonstration** (gratuite, 1 mois) : essai en entreprise ;
- **Professionnelle** (abonnement annuel, Lemon Squeezy) : tout usage professionnel.

Au premier `eunit run`, une fenêtre demande le type de licence. `python eunit_cli.py license` affiche
la licence ; `license choose | activate [CLÉ] | deactivate | check | buy | portal` la gère. Sur un
poste d'entreprise (domaine Active Directory ou Entra ID), une licence Personnelle déclenche un
rappel. En intégration continue, aucune fenêtre : la clé Professionnelle se donne par la variable
d'environnement `EUNIT_LICENSE_KEY`. La licence apparaît dans tous les rapports.

Le runtime cible (`target/`), les cartes (`boards/`), les exemples (`examples/`) et le code généré
sont sous **licence MIT** : ils partent dans vos firmwares sans licence e2Unit.

L'identité du produit (nom, produit Lemon Squeezy, liens d'achat) est dans
[`eunit/license/product.py`](eunit/license/product.py).

## Limites connues

- Paramètres scalaires uniquement pour les adapters générés (pointeurs/tableaux : adapter manuel).
- Pas de type 64 bits ni `double` dans l'ABI (un mot de 32 bits par valeur).
- L'émulateur ne donne pas de cycles ; les cycles cible incluent l'appel de l'adapter.
- Couverture de code (gcov) non intégrée.
