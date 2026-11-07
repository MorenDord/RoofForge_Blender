# RoofForge 0.2.0 — scope and implementation gates

**Working branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Base:** validated user-facing 0.1.0 alpha  
**Target:** Blender 5.0+  
**Status:** implementation in progress

## User-confirmed priorities

1. Support **simple** polygon contours with up to 64 boundary edges: convex, concave, narrow notches and non-uniform edge lengths. More than 64 edges are outside the 0.2.0 target; self-intersecting contours, zero-length projected edges and multiple independent boundary loops must be diagnosed, not silently repaired.
2. Do not require selecting vertices or edges in Edit Mode. Selecting the mesh object is enough; RoofForge discovers one outer boundary from the mesh topology. A face mesh uses its boundary edges; a wire-only mesh uses its closed wire loop.
3. Give every boundary edge/slope its own pitch angle. Start with a compact list of numeric fields; a numbered top-view pitch map is not in this milestone.
4. Pitch edits trigger a debounced live rebuild. Keep the last valid roof visible until the replacement is built and validated. Coalesce rapid changes; never regenerate inside a UI draw callback.
5. Provide an optional geometric eave overhang in centimeters. Extend every boundary strip in its own support plane and weld adjacent strips along their actual 3D intersection ridge. Support simple concave offsets whenever the resulting boundary is simple; reject collapsed or self-intersecting offsets.

Everything else in the 1.0 roadmap is deferred: ridge/valley/hip profiles, standing seams, UV, LOD, export, complex material handling and detach/relink.

## Geometry contract

- Calculations remain in source-object local coordinates and retain all XYZ boundary coordinates.
- Each source boundary edge owns one stable slope ID and one pitch angle.
- Its plane must pass through both endpoint vertices and satisfy the requested total inclination. A mathematically incompatible pitch must fail with a clear message; never clamp it silently.
- The output must cover the source polygon exactly within scale-aware tolerances. Internal surface edges must be shared, and each boundary edge must be covered by the generated surface boundary.
- Output facets must retain source-slope identity and be planar. The final thickness shell must pass edge- and vertex-manifold validation.
- For this milestone, "arbitrary contour" means any valid, non-self-intersecting single-loop polygon. Holes and multiple loops are deferred unless they fall out of the boundary model without destabilizing the core.
- The existing weighted wavefront prototype is **not approved for production integration as-is**. The distance-field prototype is also not an acceptable replacement: its transition patches are approximate and its current uniform refinement has poor scaling.

## Performance is a release gate

Do not choose a solver based only on correctness fixtures. The next geometry implementation must be benchmarked before Blender UI integration.

Benchmark separately:
- boundary extraction;
- geometry solver (event generation and topology updates);
- facet assembly / welding / validation;
- Blender mesh datablock creation;
- complete live rebuild.

Use deterministic synthetic inputs at 8, 16, 32 and 64 boundary edges. **64 edges is the upper performance and acceptance target for 0.2.0; routine CI does not benchmark 128-edge contours.** Include concave adversarial fixtures (L, U, narrow neck, repeated reflex vertices and near-simultaneous events). Record median and p95 wall time over repeated runs, peak triangle/face count and memory where practical. Run the benchmarks on the same CI runner so revisions are comparable.

Optimization requirements:
- no global uniform four-way refinement of the whole polygon at every depth;
- do not rescan every reflex vertex against every edge after every local event if a conservative spatial index or local event invalidation can reduce the candidate set;
- use stable IDs and generation stamps so stale events are discarded cheaply;
- avoid rebuilding/validating unchanged state more than necessary;
- retain deterministic ordering and all geometric/topological validation gates.

Do not invent a latency guarantee before measuring the first valid implementation. Once the baseline is recorded, set explicit preview/final budgets and fail CI on significant regressions.

## Input acquisition already started

The branch now has automatic object-boundary acquisition:
- face meshes use edges incident to exactly one face;
- wire-only meshes use their loose edges;
- one closed connected loop is ordered deterministically;
- mesh selection flags are ignored;
- multiple loops, branches and malformed boundaries are rejected.

Blender background smoke coverage is being expanded for both wire and face meshes in Object and Edit Mode with all mesh elements deselected.

## Acceptance checklist for 0.2.0

- [ ] User-facing generator uses the new general concave solver, not the old convex-only plane envelope.
- [ ] Seeded simple polygon corpus covers convex/concave contours, random vertex positions, clockwise/counter-clockwise winding and mixed positive per-edge pitch.
- [ ] Every accepted input produces complete domain coverage, planar facets, a fully covered outer boundary and a valid closed manifold shell.
- [ ] Invalid/self-intersecting/degenerate inputs fail with actionable diagnostics.
- [ ] Object selection alone is enough to detect the contour, in Object Mode and Edit Mode, on both wire-only and face meshes.
- [ ] Per-edge pitch values remain mapped to the correct source edge after rebuilds.
- [x] Changing a pitch causes one coalesced Live Update using the selected 0–1000 ms delay; rapid changes cancel the pending timer and replace it.
- [ ] A failed update leaves the last valid output unchanged.
- [ ] Performance baselines exist at 8–64 edges, with 64 as the maximum 0.2.0 target; preview and final thresholds are defined from measured results.
- [x] Convex and tested concave L/U overhangs preserve every edge's source support plane. Adjacent strips are welded along the common 3D ridge using edge splitting; any leftover ridge segment is one outer connector. Mixed-height convex XYZ overhang is covered.
- [x] Live Update delay is adjustable from 0 to 1000 ms, default 0 ms; no intentional debounce at zero. Ridge/valley/hip, seam, UV, LOD or export controls remain out of scope.
- [ ] Blender 5.0.1 background smoke and official extension package validation pass; manual viewport QA remains a separate gate.

## Current known mathematical risk

The custom Python weighted-wavefront solver is integrated into the Blender generator for flat-Z eaves. It handles the tested convex/concave radial, L/U and selected wavy L/U families with per-edge pitch. This is still not a generic simultaneous-event solver: multi-notch and unsupported mixed event groups remain known failures and are rejected with diagnostics. Mixed-height contours stay on the existing 3D support-plane path; preserve XYZ and explicitly reject incompatible geometry. Do not flatten or silently modify user geometry.

## Результаты сравнительных замеров (CI, 6–7 ноября 2026)

Все времена ниже получены на GitHub Actions Linux runner. Это сравнительные замеры, а не обещание производительности на машине пользователя. Целевой диапазон RoofForge 0.2.0 — **8–64 ребра**.

### Rust-кандидат (surfer2 0.1.0: skeleton + DCEL extraction + геометрические проверки)

На 64 рёбрах:
- Выпуклый контур: около 0.56 мс с равным pitch и 0.40 мс с индивидуальным pitch.
- Асимметричный вогнутый контур: около 0.42 мс с равным pitch и 0.39 мс с индивидуальным pitch.
- 12-рёберный multi-notch: около 0.09 мс с равным pitch и 0.085 мс с индивидуальным pitch.
- Малые событийные L/U fixtures, включая несколько порядков split/collapse и U с тремя needle-событиями, проходят.
- Основной L-контур 8×8 с индивидуальными углами всё ещё теряет два ската; симметричные одновременные события остаются отказными (неверная площадь / ребро с четырьмя использованиями).

Исходный код `surfer2 0.1.0` также подтверждает конкретный пробел: после weighted-событий Rust-версия очищает очередь локального refinement, не выполняя её, тогда как исходный C++-движок обрабатывает эту очередь. Это объясняет часть потери фасетов и не исправляется подбором коэффициентов скоростей. См. [weighted refinement в surfer2-rs](https://github.com/atsyplenkov/surfer2-rs/blob/master/src/triangulation/refine.rs).

Это только benchmark-кандидат: он не встроен в Blender, не имеет готовых runtime-сборок для Windows/macOS/Linux и пока не проходит полный корпус геометрии.

### Собственный Python weighted wavefront (подключён в 0.2.0-alpha.6 для flat-Z контуров)

Alpha 0.2.0-alpha.6 final CI runs [42335026739](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335026739) (push) and [42335029848](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335029848) (PR) both passed on code commit `0a45005bcd8196728b39dd433fff94d36d8939a0`: Python 3.11/3.13, support-plane strip/ridge welding regressions, flat and mixed-Z custom-pitch eaves, concave L/U eaves, Blender 5.0.1 smoke, ZIP validation, geometry/legacy/Rust/profile benchmarks.

Симметричный concave fixture с чередованием радиусов 10.0/8.6 и одинаковым уклоном 35° проходит на 8/16/32/64 рёбрах. Затем тот же контур проходит с индивидуальным детерминированным профилем углов:

`pitch[i] = 32 + 4 sin(1.371 i) + 2.5 cos(0.613 i)` градусов.

Все времена — median трёх повторов на GitHub Actions Linux runner. Это сравнительные данные, не latency-гарантия на рабочей станции.

| Рёбер | Equal trace | Equal surface | Variable trace | Variable surface | Variable facets / vertices |
|---:|---:|---:|---:|---:|---:|
| 8 | 0.47 мс | 1.37 мс | 0.84 мс | 2.19 мс | 30 / 32 |
| 16 | 2.40 мс | 5.10 мс | 6.14 мс | 13.47 мс | 133 / 134 |
| 32 | 7.77 мс | 17.09 мс | 35.13 мс | 74.13 мс | 525 / 526 |
| 64 | 21.34 мс | 32.19 мс | 212.63 мс | 474.54 мс | 2089 / 2091 |

Отдельные волнистые L/U fixtures, 64 ребра, variable pitch, median трёх повторов:

| Форма | Trace | Сборка поверхности | Фасет / вершины |
|---|---:|---:|---:|
| Wavy L | 159.66 мс | 352.61 мс | 2038 / 2041 |
| Wavy U | 149.17 мс | 360.82 мс | 2085 / 2086 |

Оба сценария проходят полное покрытие XY-контура, сохранение slope metadata и закрытый manifold-shell. Это benchmark тех же геометрий, что используются в 64-edge L/U регрессионных тестах.
На предельном variable-pitch случае сборка поверхности первоначально занимала 28.50 секунды. Причина — T-junction pass проверял все вершины для каждого ребра каждой фасеты. После добавления трёх отсортированных координатных индексов с выбором наиболее узкого диапазона и сохранения точной 3D-проверки то же время снизилось до 474.54 мс (примерно в 60 раз). Это уже на порядок практичнее, но около половины секунды на сложном 64-рёберном contour пока остаётся верхним, не идеальным live-preview временем.

Для 64 рёбер переменный профиль создаёт 2 089 фасет и 2 091 вершину. Все фасеты сохраняют source-slope metadata; проверки подтверждают полное покрытие исходного XY-контура, shell edge/vertex manifold и отсутствие граней ниже локальной координатной точности.

### Исправление площади малых фасет

Глобальный критерий `eps * model_scale²` ошибочно отбрасывал маленькие, но хорошо сформированные фасеты на большой крыше. Теперь порог площади каждой грани равен глобальной линейной координатной точности, умноженной на длину её собственной самой длинной стороны. Таким образом:
- небольшие, но локально разрешимые треугольники не отвергаются только из-за размера всей модели;
- почти нулевые «иглы» с высотой ниже линейной точности по-прежнему дают `ZERO_AREA_FACE`.

Есть отдельные тесты на обе стороны этого контракта; тест на локально неразрешимый sliver остаётся обязательным.

### Ограничения и статус кандидата

- Регрессионное покрытие теперь включает три класса: симметричное радиальное concave-семейство, асимметричный радиальный профиль и волнистые L/U-контуры с индивидуальными уклонами на 64 рёбрах. Это всё ещё детерминированные fixtures, не seeded/random corpus и не доказательство для произвольного простого многоугольника.
- Для 64-рёберных wavy L и U проверяются complete trace, полное projected-area coverage, facet slope metadata, сборка surface и замкнутая manifold-shell.
- Generic multiple-split и некоторые смешанные event groups всё ещё завершаются диагностической ошибкой; near-simultaneous adversarial combinations надо расширить.
- `build_moving_lines()` пока отвергает разные Z карнизов. XYZ-вход не меняется, но mixed-height concave solver не реализован.
- `addon/operators/generate.py` использует `build_wavefront_roof_surface()` для flat-Z контуров; mixed-Z остаётся на 3D support-plane envelope path.
- В 0.2.0-alpha.6 `build_roof_payload()` кэширует проверенную верхнюю поверхность по source-object ID, XYZ-контуру, pitch и свесу. Толщина не входит в ключ: thickness-only Live Update перестраивает shell без повторного wavefront/plane-envelope расчёта.
- `create_roof_mesh_data()` записывает face attributes через `foreach_set`, сокращая Python-цикл по каждой грани. Геометрический пересчёт при изменении pitch по-прежнему требуется; latency на пользовательской машине нужно оценивать вручную.

Это рабочая alpha-интеграция с известными ограничениями событий, а не универсальный production solver. PR остаётся draft для сбора viewport QA.

### Исторический Python spatial solver 2.9 (только тестовая копия)

На 64 рёбрах:
- Выпуклый радиальный контур: около 342 мс с равным pitch и 530 мс с индивидуальным.
- Вогнутый радиальный контур: около 712 мс с равным pitch и 491 мс с индивидуальным.
- Плоские L/U: около 3.2–5.4 мс.
- Плоский 12-рёберный multi-notch: около 11–15 мс.
- cProfile для вогнутого 64-рёберного случая показывает около 2.23 с (equal) и 1.44 с (variable) с включённой инструментализацией. Остаются затраты как на события wavefront, так и на сборку граней.
- Текущие non-planar L/U XYZ fixtures не проходят строгую проверку соответствия соседних support planes / manifold. Два альтернативных all-pairs эксперимента также оставляют внутренние открытые рёбра и не приняты как fallback.

Вывод: старый Python solver годится как сравнительный эталон для малых плоских форм, но даже после оптимизаций слишком медленный для полноценного live rebuild сложных 64-рёберных контуров. Rust-кандидат достаточно быстр, однако его топологические сбои на важных concave-сценариях блокируют production integration.



### Blender UI, сантиметры, свес и Live Update — интегрированы в 0.2.0-alpha.6

- addon/properties.py: коллекция pitch-настроек по каждому edge, ссылки на исходный и сгенерированный объект, статус и переключатель Live Update.
- addon/operators/prepare.py: считывает контур и создаёт нумерованный список углов.
- addon/ui/panel.py: поля Edge NN (Vx→Vy), Thickness (cm), Eave Overhang (cm), Live Update, Update Delay и Create/Update; Default Pitch и Validate удалены.
- addon/live_update.py: настраиваемый debounce 0–1000 мс, по умолчанию 0 мс, перестройка на Blender main thread, rollback при ошибке, rename guard и защита от удалённой крыши.
- addon/operators/generate.py: при удалении результата stale pointer очищается; новая крыша линкуется в root collection активной сцены и проверяется через `scene.objects` перед успешным ответом.
- Thickness, per-edge pitch и свес запускают Live Update. При изменении только thickness верхняя поверхность берётся из cache.
- Свес и толщина задаются в сантиметрах. Для каждого граничного ребра создаётся одна полоса на его исходной support plane. Соседние полосы встречаются на фактической 3D-линии пересечения плоскостей; перекрывающаяся часть общей линии сваривается через split длинной боковой кромки. Остаточный участок ridge является одной внешней кромкой, поэтому свесы не выступают друг за друга. Reflex L/U offsets разрешены, пока внешний контур остаётся простым.
- UI-план крыши с графической нумерацией и подсветкой соответствующего edge пока отсутствует; в alpha поля соответствуют детерминированному порядку обхода.

### Ограничения, явно оставленные для пользовательской проверки

- Flat-Z L/U и ряд радиальных/волнистых семейств с индивидуальными углами проходят тесты и доступны через UI.
- Два multi-notch теста временно помечены как skipped с причиной: unresolved same-time split/collapse batches. Это известное ограничение alpha, а не успешная поддержка всех multi-notch contours.
- Mixed-Z контуры сохраняют XYZ и идут по прежнему 3D support-plane envelope; сложные вогнутые mixed-Z shapes могут быть отклонены.
- Пакет 0.2.0-alpha.6 будет собран после прохождения Blender smoke и официального Extension Validator; ожидаемое smoke-покрытие включает flat/mixed-Z variable-pitch overhang, centimeter conversion, defaults and removal of Validate/Default Pitch UI. Результат всё ещё требует ручного viewport QA пользователя.

### Ограничение размера

- 64 ребра — верхняя граница функционального и performance target для 0.2.0.
- Обычный CI benchmark и cProfile ограничены диапазоном 8, 16, 32 и 64 рёбер.
- Контуры больше 64 рёбер не входят в критерии приёмки этой версии; отдельная оптимизация для 128 рёбер не требуется.

## Точный статус готовности 0.2.0-alpha.6

- [x] Автоопределение одного замкнутого контура в Object/Edit Mode без выделения вершин/рёбер; wire и face mesh.
- [x] Per-edge pitch UI с нумерованными полями и vertex-pair подписью; новые поля default 30°.
- [x] Flat-Z weighted wavefront подключён к пользовательскому генератору.
- [x] Mixed-Z контуры сохраняют XYZ и используют 3D support-plane path.
- [x] Thickness по умолчанию 1 см; Eave Overhang и Thickness вводятся в сантиметрах с учётом Scene Unit Scale.
- [x] Validate Roof operator и Default Pitch property удалены; Create / Update выполняет валидацию.
- [x] Live Update с задержкой 0–1000 мс, default 0 мс, rollback last-valid roof и rename guard.
- [x] Ridge-welded eaves: flat variable-pitch, mixed-Z variable-pitch convex, concave L/U variable-pitch overhang проходят тесты; self-intersect/collapsed offset отклоняется.
- [x] Blender 5.0.1 smoke: cm conversion, 30°/1 cm defaults, UI simplification, flat and mixed-Z variable-pitch overhang, concave L/U with nonzero overhang, oversized U offset rejection, cache and delete/recreate.
- [x] Clean Extension ZIP 0.2.0-alpha.6 собран и принят официальным Blender Extension Validator.
- [x] CI push `42335026739` и PR `42335029848` на code commit `0a45005...` прошёл; Python 3.11/3.13 и все geometry/legacy/Rust/profile/Blender package jobs успешны.
- [ ] Универсальная обработка всех multi-notch / simultaneous split-collapse комбинаций.
- [ ] Общий solver для mixed-height concave XYZ contours.
- [ ] Визуальная подсветка соответствия ската его ребру и ручной viewport QA.

Итог: 0.2.0-alpha.6 будет готова к пользовательской проверке после зелёного CI; это не стабильный 0.2.0 release. PR остаётся draft до получения обратной связи и исправления обнаруженных ошибок.
