# 1. Prise en main d'e2Unit

[English](../tutorials/01-getting-started.md) | **Français**

Lancer les tests d'exemple sur PC et lire leurs résultats. Ce tutoriel suppose e2Unit installé et
`eunit.local.mk` renseigné (voir le [sommaire](README.md)).

## Lancer une suite

Une **suite** regroupe les tests d'une fonction (ou de plusieurs). Celle de `emath_sin` est dans
[`examples/emath/tests/sin`](../../examples/emath/tests/sin) :

```
cd examples/emath
make test/sin
```

```
eunit: generated build\gen\eunit_suite.c
eunit: generated build\gen\suite.mk
eunit: building build/host/sin.dll
e2Unit 0.1.0: suite sin, 3 test(s) on host
eunit: Personal License - Non-commercial use only
  [PASS ] SIN-001 accuracy over the full turn (65536 samples, 0.01 s)
  [PASS ] SIN-002 exact values on the axes (4 samples, 0.00 s)
  [PASS ] SIN-003 odd symmetry and range (65535 samples, 0.01 s)
eunit: PASS - 3 passed, 0 failed, 0 errors, 0 skipped in 0.02 s - reports in build\report\host
```

En trois lignes, make a :

1. **généré** le code d'interface C (`eunit_suite.c`) à partir de la spécification `sin.yaml` ;
2. **compilé** une bibliothèque PC (`sin.dll`) avec `emath_sin.c` et le runtime e2Unit ;
3. **exécuté** les trois tests : 131 075 appels de `emath_sin` en 20 ms.

La ligne `eunit: Personal License ...` rappelle la licence utilisée. Au tout premier lancement, une
fenêtre demande de la choisir (voir le [sommaire](README.md)).

`make test` sans argument lance toutes les suites de l'exemple. `make -k test` continue après un échec.

## Lire le détail

Chaque test contient une ou plusieurs **vérifications**. L'option `-v` les affiche toutes :

```
cd tests/sin
make EUNIT_RUN_OPTS=-v
```

```
  [PASS ] SIN-001 accuracy over the full turn (65536 samples, 0.01 s)
         1. [PASS] |y - round(32767 sin(pi angle / 32768))| <= 2 LSB: 65536 samples, max |err| 2 (tol abs=2)
         2. [SKIP] execution time: no cycle counter on this runner
```

- La vérification 1 compare chaque sortie à la sinusoïde idéale : l'erreur maximale est de 2 LSB,
  la tolérance aussi. Le test passe, sans marge.
- La vérification 2 porte sur le temps d'exécution : elle n'a de sens que sur la carte (tutoriel
  [6](06-ra4e1-jlink.md)). Sur PC, elle est **SKIP**, pas en échec.

Les verdicts possibles :

| Verdict | Signification |
|---|---|
| PASS | toutes les vérifications passent |
| FAIL | au moins une vérification en échec : la fonction ne respecte pas sa spécification |
| ERROR | le test n'a pas pu s'exécuter : spécification invalide, stimulus hors du type C, fonction bloquée, faute CPU |
| SKIP | rien n'a pu être vérifié sur ce runner (cycles sur PC) |

Le code retour suit le verdict : 0 si tout passe, 1 en cas d'échec, 2 en cas d'erreur. Un serveur
d'intégration continue s'arrête donc sur un test faux.

## Les rapports

Chaque exécution écrit dans `build/report/<runner>/` :

| Fichier | Contenu |
|---|---|
| `junit.xml` | format JUnit, lu par Jenkins, GitLab CI, etc. |
| `results.json` | tous les résultats et statistiques, pour d'autres outils |
| `<suite>_host.xlsx` | rapport Excel : une feuille de synthèse, une feuille avec une ligne par vérification (exigence, test, résultat) |

La feuille Excel *Tests* est la matrice de traçabilité : la colonne *Requirement* reprend
l'exigence déclarée dans la spécification (`EMATH-SIN-01`...).

## Les graphes

`--plot` enregistre un PNG par vérification en échec ; `--plot-all` les enregistre toutes :

```
make EUNIT_RUN_OPTS="--plot build/plots --plot-all"
```

En haut, la sortie et la valeur attendue ; en bas, l'erreur. Pour `emath_sin`, l'erreur reste dans
±2 LSB sur tout le tour :

![SIN-001 : sortie, sinusoïde idéale et erreur](../img/plot-sin-error.png)

## Ce que contient une suite

```
tests/sin/
  sin.yaml     la spécification : sources, fonction, tests
  Makefile     3 lignes
  build/       généré : code, bibliothèque, firmware, rapports
```

Le Makefile est identique pour toutes les suites, au nom du fichier près :

```make
EUNIT_ROOT := ../../../..
SUITE      := sin.yaml
include $(EUNIT_ROOT)/mk/eunit.mk
```

`make list` affiche les fonctions et les tests d'une suite, `make clean` efface `build/`. Le
[tutoriel 2](02-tester-une-fonction.md) écrit une suite complète.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `gcc: not found` ou `cc1.exe` qui ne démarre pas | chemin de `HOST_CC` faux, ou dossier `bin` de MSYS2 absent du `PATH` dans `eunit.local.mk` |
| `PyYAML is required` | `pip install pyyaml` dans le Python désigné par `PY` |
| `cannot load ...dll` | Python 32 bits avec un gcc 64 bits (ou l'inverse) : les deux doivent être 64 bits |
| `... does not match suite ...: rebuild it` | bibliothèque compilée depuis une autre version de la spécification : `make clean`, puis `make` |
