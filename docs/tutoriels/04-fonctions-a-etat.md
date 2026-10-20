# 4. Fonctions à état

[English](../tutorials/04-stateful-functions.md) | **Français**

Tester une fonction qui garde un état entre deux appels : un RMS glissant. Le prototype ne suffit
plus, on écrit un petit **adapter** en C.

## La fonction

[`emath_rms.c`](../../examples/emath/src/emath_rms.c) calcule la valeur efficace des 2ⁿ derniers
échantillons. Le contexte (fenêtre, somme des carrés) est passé par pointeur :

```c
bool     emath_rms_init(emath_rms_t *ctx, uint8_t log2n);   /* false si log2n > 8 */
uint16_t emath_rms_update(emath_rms_t *ctx, int16_t x);     /* ajoute x, rend le RMS */
```

Un pointeur ne se génère pas : quel contexte passer, et où le garder entre deux appels ? C'est le
rôle de l'adapter.

## 1. L'adapter

Un adapter reçoit les entrées et rend les sorties sous forme de mots de 32 bits. On l'écrit avec
la macro `EUNIT_ADAPTER(nom)` dans
[`rms_adapter.c`](../../examples/emath/tests/rms/rms_adapter.c) :

```c
#include "eunit.h"
#include "emath.h"

static emath_rms_t rms_ctx;   /* le contexte vit ici, entre les appels */

EUNIT_ADAPTER(rms_init)
{
    out[0] = emath_rms_init(&rms_ctx, (uint8_t)in[0]) ? 1 : 0;
}

EUNIT_ADAPTER(rms_update)
{
    out[0] = (int32_t)emath_rms_update(&rms_ctx, (int16_t)in[0]);
}
```

## 2. La spécification

Le fichier est ajouté aux sources. Côté `functions`, `custom: true` dit à e2Unit de ne pas générer
l'adapter. Le prototype ne décrit plus que l'interface vue par les tests :

```yaml
build:
  sources: [../../src/emath_rms.c, ../../src/emath_isqrt.c, rms_adapter.c]
  includes: [../../src]
  headers: [emath.h]

models: [../emath_ref.py]

functions:
  rms_init:
    prototype: "bool rms_init(uint8_t log2n)"
    custom: true
    returns: ok
  rms_update:
    prototype: "uint16_t rms_update(int16_t x)"
    custom: true
    returns: rms
```

Un adapter peut aussi rendre plusieurs valeurs : `outputs: "uint32_t acc, int16_t last"`
déclare des sorties supplémentaires, écrites dans `out[1]`, `out[2]`...

## 3. Setup et reset

```yaml
  - id: RMS-003
    title: transients and full scale, 256 samples window
    requirement: [EMATH-RMS-02, EMATH-RMS-03]
    setup:
      - rms_init: [8]                 # fenêtre de 2^8 = 256 échantillons
    call: rms_update
    stimuli:
      x:
        segments:
          - {n: 300, dc: 0}
          - {n: 600, dc: -32768}
          - {n: 600, dc: 32767}
          - {n: 600, square: {amp: 10000, period: 50}}
          - {n: 1000, noise: 30000}
    checks:
      - desc: identical to the exact sliding window model
        expect: rms_window(x, 8)
      - desc: full scale negative input gives 32768 (no overflow)
        window: [556, 900]
        expect: 32768
      - desc: never above full scale
        max: 32768
```

- **Reset.** Avant chaque test, e2Unit remet le code dans son état de démarrage : la bibliothèque
  PC est rechargée, la carte est réinitialisée. `rms_ctx` et toutes les variables statiques
  repartent de zéro, et l'ordre des tests n'a pas d'influence. `reset: false` enchaîne au
  contraire sur l'état laissé par le test précédent.
- **Setup.** `setup:` appelle des fonctions avant les stimuli, ici l'initialisation.
- Les 3100 échantillons sont ensuite passés **dans l'ordre** à `rms_update`.

## 4. Le modèle

La référence exacte d'un RMS glissant tient en quelques lignes de numpy, dans
[`emath_ref.py`](../../examples/emath/tests/emath_ref.py) :

```python
def rms_window(x, log2n):
    """floor(sqrt(mean of the squares of the last 2^log2n samples)), zeros before start."""
    n = 1 << int(log2n)
    sq = np.asarray(x, dtype=np.int64) ** 2
    csum = np.concatenate(([0], np.cumsum(sq)))
    i = np.arange(len(sq))
    window = csum[i + 1] - csum[np.maximum(i + 1 - n, 0)]
    return np.array([math.isqrt(int(v) >> int(log2n)) for v in window], dtype=np.int64)
```

Le modèle calcule la fenêtre par sommes cumulées, le C par tampon circulaire : deux méthodes
différentes, qui doivent donner exactement le même résultat.

## 5. Résultat

```
  [PASS ] RMS-003 transients and full scale, 256 samples window (3100 samples, 0.01 s)
         1. [PASS] identical to the exact sliding window model: 3100 samples, max |err| 0 (tol exact)
         2. [PASS] full scale negative input gives 32768 (no overflow): 344 samples, max |err| 0 (tol exact)
         3. [PASS] never above full scale: 3100 samples within bounds, observed [0, 32768]
```

Pour un signal, l'axe des graphes est l'index de l'échantillon :

![RMS-003 : montée, pleine échelle à 32768, carré à 10000, bruit](../img/plot-rms-transients.png)

On y lit la montée sur 256 échantillons, le plateau à 32768 (pleine échelle négative, sans
débordement), la descente vers 10000 sur le carré, puis le bruit.

## Tester une fonction `static`

Une fonction `static` n'est pas visible depuis un autre fichier. L'adapter peut inclure le fichier
source lui-même :

```c
#include "eunit.h"
#include "module.c"      /* donne accès aux fonctions et variables static */

EUNIT_ADAPTER(filter_step) { out[0] = filter_step((int16_t)in[0]); }
```

Dans ce cas, `module.c` ne doit pas figurer aussi dans `build: sources:`.

Le [tutoriel 5](05-cible-sans-carte.md) compile ces mêmes suites pour le microcontrôleur.
