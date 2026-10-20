# 7. Intégration

[English](../tutorials/07-integration.md) | **Français**

Organiser les suites d'un projet, les lancer en intégration continue, et exécuter les tests à
l'intérieur d'une application existante plutôt que dans le firmware de test.

## Organiser les suites

L'exemple suit une organisation qui se transpose à un projet :

```
examples/emath/
  Makefile             lance un but sur toutes les suites
  src/                 le code testé
  tests/
    emath_ref.py       modèles de référence partagés
    sin/  mulq15/  atan2/  pow/  isqrt/  rms/     une suite par module
    all/               suite globale (include des autres)
```

Le `Makefile` de tête ([`examples/emath`](../../examples/emath)) applique un but à chaque suite :

```
make test              # toutes les suites sur PC
make -k test-emu       # toutes, dans l'émulateur, sans s'arrêter au premier échec
make target            # un firmware par suite, plus le firmware global
make test/rms          # une seule suite
```

Pour ajouter une suite, créer son dossier et l'ajouter à la liste `SUITES` de ce Makefile.

## Intégration continue

Le code retour donne le verdict (0 PASS, 1 FAIL, 2 erreur) et chaque exécution écrit un
`junit.xml`. Exemple d'étape Jenkins sur un agent Windows :

```groovy
stage('Unit tests') {
    steps {
        bat 'make -C examples/emath -k test test-emu'
    }
    post {
        always {
            junit 'examples/emath/tests/**/build/report/**/junit.xml'
            archiveArtifacts artifacts: 'examples/emath/tests/**/build/report/**/*.xlsx', allowEmptyArchive: true
        }
    }
}
```

- `test` (PC) et `test-emu` (binaire ARM émulé) ne demandent pas de carte : ils tournent sur
  n'importe quel agent.
- `test-target` demande un agent avec une carte et une sonde J-Link branchées.
- Le nom de chaque suite JUnit porte le runner (`sin.host`, `sin.emu`) : les résultats PC et cible
  apparaissent séparément.

Les chemins des outils de l'agent vont dans son propre `eunit.local.mk`.

## Tester dans une application existante

Le firmware de test d'e2Unit est minimal : pas de clock, pas de périphérique, pas de RTOS. Pour
tester une fonction **dans son environnement réel** (horloges réglées, caches, autres tâches), on
ajoute le runtime à l'application.

### Fichiers à ajouter au projet (e² studio, CubeIDE...)

| Fichier | Rôle |
|---|---|
| `target/src/eunit_runtime.c` | runtime |
| `target/port/cortex-m/eunit_port_cortexm.c` | compteur de cycles, barrière mémoire |
| `build/gen/eunit_suite.c` | adapters générés depuis la spécification |
| vos adapters (`EUNIT_ADAPTER`), s'il y en a | fonctions à état |

Chemin d'include : `target/include`. Le fichier généré se produit avec :

```
python eunit_cli.py gen suite.yaml --out build/gen
```

Ne **pas** ajouter `eunit_startup.c` ni `eunit_main.c` : l'application a les siens.

### Appel dans la boucle principale

```c
#include "eunit.h"

void hal_entry(void)
{
    /* ... initialisation de l'application ... */
    eunit_init();
    for (;;) {
        eunit_poll();          /* sert une requête du PC, s'il y en a une */
        /* ... reste de la boucle ... */
    }
}
```

`eunit_poll()` rend la main tout de suite quand il n'y a rien à faire. Quand un lot arrive, il
l'exécute en entier avant de rendre la main : réduire `EUNIT_BUF_WORDS` (option du compilateur,
2048 mots par défaut) si un chien de garde ou une tâche temps réel ne le supporte pas.

Optionnellement, dans le `HardFault_Handler` de l'application, appeler `eunit_fault(pc)` : le PC
voit alors la faute (`CPU fault at PC ...`) au lieu d'un délai dépassé.

### Lancer

```
python eunit_cli.py run suite.yaml --runner jlink --elf Debug/app.elf --device R7FA4E10D
```

L'application est flashée et lancée comme d'habitude (e² studio, J-Flash...), puis la session de
debug est fermée pour libérer la sonde. e2Unit réinitialise la carte avant chaque test :
`eunit_init()` doit être atteint dans les 5 secondes qui suivent le reset.

## Résumé des commandes

| Commande | Effet |
|---|---|
| `make` / `make test` | build PC + tests sur PC |
| `make test-sim` | tests par le protocole cible, sur PC |
| `make target` | firmware de test de la carte (`BOARD=ra4e1` par défaut) |
| `make test-emu` | firmware dans l'émulateur, comparé au PC |
| `make flash` | programme le firmware par J-Link |
| `make test-target` | flash + tests sur carte, comparés au PC |
| `make list` | fonctions et tests de la suite |
| `make clean` | efface `build/` |
| `EUNIT_RUN_OPTS="-v --plot build/plots"` | détail des vérifications, graphes |
| `JLINK_OPTS="--serial N --speed 12000"` | choix et vitesse de la sonde |
