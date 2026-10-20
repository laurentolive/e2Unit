# 3. Stimuli et vérifications

[English](../tutorials/03-stimuli-checks.md) | **Français**

Toutes les façons de générer les entrées d'un test et de vérifier ses sorties, illustrées par les
suites d'exemple ([`examples/emath/tests`](../../examples/emath/tests)).

## Stimuli

Chaque paramètre de la fonction reçoit un générateur, sous `stimuli:`.

| Forme | Exemple | Valeurs |
|---|---|---|
| constante | `k: 5` | 5, répété |
| liste | `x: [0, 16384, -32768]` | ces valeurs |
| plage entière | `x: {range: [-32768, 32767]}` | toutes, bornes incluses (`step:` en option) |
| répartition | `x: {linspace: [-32768, 32767, 257]}` | 257 valeurs régulières, arrondies pour un entier |
| aléatoire | `x: {random: [0, 4294967295], n: 200000}` | uniforme, **reproductible** |
| expression | `x: {expr: "(i // 3 + 1) ** 2 + i % 3 - 1", n: 196605}` | fonction de l'index `i` |
| signal | `x: {segments: [...]}` | morceaux de signal (voir ci-dessous) |
| fichier | `x: {file: mesure.npy}` | `.npy` ou `.csv` |

**Aléatoire reproductible.** La graine par défaut dépend de l'identifiant du test et du nom du
paramètre : deux exécutions tirent les mêmes valeurs, un échec se reproduit. `seed:` fixe une
autre graine.

**Expression.** L'exemple ci-dessus ([`isqrt.yaml`](../../examples/emath/tests/isqrt/isqrt.yaml))
produit k² - 1, k² et k² + 1 pour k = 1 à 65535 : tous les carrés parfaits et leurs voisins, là
où une racine entière se trompe.

**Signal par segments.** Chaque segment a une longueur `n` et additionne des composantes :

```yaml
x:
  segments:
    - {n: 300, dc: 0}
    - {n: 600, dc: -32768}
    - {n: 600, sine: {amp: 20000, period: 64, phase: 90}}
    - {n: 600, square: {amp: 10000, period: 50, duty: 0.5}}
    - {n: 500, ramp: [0, 1000], noise: 50}
```

La phase de la sinusoïde est continue d'un segment à l'autre ; `period` est en échantillons.

### Combiner plusieurs paramètres

| `combine:` | Règle | Exemple |
|---|---|---|
| `zip` (défaut) | appel *i* avec la valeur *i* de chaque paramètre ; même longueur, les constantes sont répétées | `a: [1, 2, 3]`, `b: 7` → 3 appels |
| `grid` | toutes les combinaisons | 257 × 257 → 66 049 appels |

Une valeur qui ne tient pas dans le type C du paramètre est une **erreur**, jamais tronquée.

## Vérifications

Chaque élément de `checks:` est une vérification, rapportée comme une étape du test.

### Valeur attendue : `expect`

```yaml
- desc: "|angle - atan2(y, x)| <= 1 LSB, modulo one turn"
  expect: atan2_bin(y, x)
  tolerance: {abs: 1, modulo: 65536}
```

`expect` est une liste de valeurs, un nombre, ou une **expression Python** qui voit :

| Nom | Contenu |
|---|---|
| paramètres et sorties | tableaux numpy, par leur nom (`a`, `b`, `p`...) |
| `i`, `n` | index de l'échantillon, nombre d'échantillons |
| `np`, `sin`, `sqrt`, `pi`, `clip`, `where`... | numpy |
| `sat(x, 'int16_t')` | saturation à la plage d'un type C |
| `wrap(x, 'uint8_t')` | débordement en complément à 2, comme en C |
| `isqrt(x)` | racine entière exacte |
| `shift(x, k)` | signal retardé de `k` échantillons |
| fonctions des `models` | modèles de référence (ci-dessous) |

Une sortie peut se vérifier par rapport à une autre. Symétrie de `emath_sin`, sur des angles de
-32767 à 32767 :

```yaml
- desc: sin(-a) = -sin(a)
  expect: -y[::-1]
```

### Tolérance

| Clé | Écart permis |
|---|---|
| (aucune) | égalité exacte |
| `abs: 2` | \|sortie - attendu\| ≤ 2 |
| `rel: 1.0e-6` | ≤ 10⁻⁶ × \|attendu\| (s'ajoute à `abs`) |
| `modulo: 65536` | écart calculé modulo 65536 : pour les angles, π et -π sont égaux |

### Bornes : `min` / `max`

```yaml
- desc: output within [-32767, 32767]
  min: -32767
  max: 32767
```

### Restreindre : `window` et `where`

```yaml
- desc: once the window is full, rms = 20000 / sqrt(2) within 2 LSB
  window: [64, null]          # échantillons 64 à la fin
  expect: 20000 / sqrt(2)
  tolerance: {abs: 2}

- desc: exact away from the origin
  where: "(x != 0) | (y != 0)"
  expect: atan2_bin(y, x)
```

`window: [début, fin]` suit la convention Python (fin exclue, `null` = jusqu'au bout).

### Temps d'exécution : `cycles`

```yaml
- desc: execution time
  cycles: {max: 200, mean: 120}
```

Vérifiée sur la carte seulement ([tutoriel 6](06-ra4e1-jlink.md)), SKIP ailleurs.

## Modèles de référence

Quand la valeur attendue ne tient pas en une ligne, on l'écrit en Python, dans un fichier déclaré
sous `models:`. Toutes ses fonctions publiques deviennent utilisables dans `expect` :

```yaml
models: [../emath_ref.py]
...
    checks:
      - desc: exact or saturated result
        expect: pow_sat(base, exp)
```

```python
def pow_sat(base, exp):
    """Exact integer power saturated to int32 (0^0 = 1)."""
    ...
```

Le modèle travaille avec les entiers exacts de Python : pas de débordement, il sert d'oracle.
Un modèle doit être **plus simple** que la fonction testée, sinon il risque de partager ses bugs.
Pour la sinusoïde, la référence est `round(32767 · sin(π · angle / 32768))` : une ligne, sans
rapport avec le polynôme du code C.

## Une bonne suite

| Test | Rôle | Exemple |
|---|---|---|
| balayage exhaustif | aucun cas oublié quand le domaine est petit | `sin` : les 65 536 angles |
| grille ou aléatoire | grand domaine, plusieurs paramètres | `atan2` : grille 257 × 257 + 100 000 points |
| cas remarquables | valeurs exactes attendues, bornes, saturation | `pow` : 46340², 46341², (-2)³¹ |
| propriété | symétrie, monotonie, invariant | `sin(-a) = -sin(a)` |

Le [tutoriel 4](04-fonctions-a-etat.md) passe aux fonctions qui gardent un état entre deux appels.
