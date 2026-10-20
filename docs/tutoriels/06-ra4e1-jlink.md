# 6. Sur carte FPB-RA4E1 avec J-Link

[English](../tutorials/06-ra4e1-jlink.md) | **Français**

Flasher le firmware de test sur un Renesas RA4E1 et exécuter les tests sur la carte, par la sonde
J-Link intégrée. On obtient le résultat réel du microcontrôleur, la comparaison bit à bit avec le
PC, et le temps d'exécution de chaque fonction en cycles CPU.

| | |
|---|---|
| Carte | FPB-RA4E1 (R7FA4E10D, Cortex-M33), J-Link OB intégré |
| Liaison | USB sur **J9** (J-Link OB), SWD, 4 MHz par défaut |
| Logiciels | SEGGER J-Link Software, Python : `pylink-square`, `pyelftools` |
| Firmware | généré par e2Unit, aucun projet e² studio nécessaire |

## 1. Vérifier la sonde

Brancher la carte par **J9**, puis :

```
python eunit_cli.py probes
```

La commande affiche le numéro de série et le nom de chaque sonde connectée. Sans sonde, e2Unit
s'arrête tout de suite avec `no J-Link probe connected (USB)`.

Si plusieurs sondes sont branchées, indiquer laquelle dans `eunit.local.mk` :

```make
JLINK_OPTS := --serial 123456789
```

pylink utilise la DLL J-Link qu'il trouve en premier. Pour en imposer une version :

```make
JLINK_OPTS := --jlink-dll "C:/Program Files/SEGGER/JLink_V942/JLink_x64.dll"
```

## 2. Flasher et exécuter

```
cd examples/emath/tests/mulq15
make test-target
```

`make test-target` enchaîne :

1. le build du firmware (`build/ra4e1/mulq15.elf` et `.hex`) et de la bibliothèque PC ;
2. la vérification que le `.elf` correspond à la spécification (hash) ;
3. la programmation du `.hex` par la sonde, puis le reset de la carte ;
4. pour chaque test : reset, lots d'appels par la mailbox, vérifications, comparaison au PC.

La sortie a la même forme qu'au [tutoriel 5](05-cible-sans-carte.md), avec `on jlink` et, sur
chaque test, le nombre de cycles mesuré : `(66049 samples, ... s, cycles max N)`.

Pour seulement flasher : `make flash`. Pour relancer sans reflasher :

```
python ../../../../eunit_cli.py run mulq15.yaml --runner jlink --elf build/ra4e1/mulq15.elf --device R7FA4E10D
```

## 3. Lire les cycles

Les vérifications `cycles` ne sont évaluées que sur la carte :

```yaml
- desc: execution time
  cycles: {max: 200}
```

```
2. [PASS] execution time: cycles min ... / mean ... / max ... over 65536 calls
```

Le compteur est le **DWT CYCCNT** du Cortex-M33, lu avant et après chaque appel :

- le coût de la mesure elle-même est mesuré au démarrage et retranché ;
- le nombre compte l'appel de la fonction **et** son adapter (quelques conversions de type) ;
- `min`, `mean` et `max` portent sur tous les appels du test : `max` donne le pire cas **observé**
  sur ces entrées, pas un pire cas garanti.

Le firmware de test tourne sur l'horloge de reset, sans attente sur la flash. Dans l'application,
à fréquence plus élevée, les cycles d'attente de la flash peuvent ajouter du temps : garder de la
marge sur les limites.

Les limites des exemples sont volontairement larges. Pour régler les vôtres, lancer une fois les
tests, lire les valeurs mesurées dans le rapport (`build/report/ra4e1/results.json` ou la colonne
*Cycles max* du fichier Excel), puis fixer `max` avec une marge.

## 4. Ce que la carte apporte

| Vérification | PC | Émulateur | Carte |
|---|---|---|---|
| résultat conforme à la spécification | oui | oui | oui |
| code compilé par le compilateur cible | non | oui | oui |
| comparaison bit à bit avec le PC | — | oui | oui |
| comportement du vrai cœur (FPU, bus, flash) | non | partiel | oui |
| cycles CPU | non | non | oui |
| durée de `mulq15` (66 055 appels) | ~0,01 s | ~0,3 s | dépend de la vitesse SWD |

## 5. Une autre carte

Une carte est décrite par un dossier `boards/<nom>/` :

| Fichier | Contenu |
|---|---|
| `board.mk` | `BOARD_CPU_FLAGS`, `BOARD_LDSCRIPT`, `BOARD_DEFS` (taille du buffer), `JLINK_DEVICE`, `BOARD_EMU_CPU` |
| `<nom>.ld` | régions `FLASH` et `RAM`, puis `INCLUDE eunit_sections.ld` |

Exemple pour [`ra4e1.ld`](../../boards/ra4e1/ra4e1.ld) :

```
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 512K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}

INCLUDE eunit_sections.ld
```

Puis `make test-target BOARD=<nom>`. Les cœurs sans DWT (Cortex-M0, M0+, M23) mesurent les cycles
avec SysTick.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `no J-Link probe connected (USB)` | câble sur le mauvais connecteur (J9), ou pilote J-Link absent |
| `J-Link: ...` à la connexion | session de debug e² studio encore ouverte : la sonde ne sert qu'à un programme à la fois |
| `e2Unit runtime not ready (no magic at 0x...)` | firmware non flashé, ou autre firmware sur la carte : `make flash` |
| `... was built from another suite version` | `.elf` plus ancien que la spécification : `make target` |
| `CPU fault at PC 0x...` | la fonction testée a planté : `arm-none-eabi-addr2line -e build/ra4e1/<suite>.elf 0x...` |
| `p identical to host` en FAIL | la cible ne calcule pas comme le PC : débordement, extension de signe, `int` de taille différente, optimisation |
