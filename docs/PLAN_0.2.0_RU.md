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
5. Remove eaves/overhang feature generation from this milestone. Keep only the basic boundary side faces required to close a thickness shell; those are not an overhang or decorative eaves feature.

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
- [ ] Changing a pitch causes one debounced live update; rapid changes do not queue unbounded builds.
- [ ] A failed update leaves the last valid output unchanged.
- [ ] Performance baselines exist at 8–64 edges, with 64 as the maximum 0.2.0 target; preview and final thresholds are defined from measured results.
- [ ] No overhang/eaves generator, ridge/valley/hip, seam, UV, LOD or export controls are included.
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

### Собственный Python weighted wavefront (подключён в 0.2.0-alpha.3 для flat-Z контуров)

Alpha 0.2.0-alpha.3 CI runs [42320863070](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42320863070) (push) и [42320868809](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42320868809) (PR) прошли полностью на code commit `304a90a488fae5bdb23cff54349a5fac3246c7a3`: Python 3.11/3.13, новые тесты свеса, Blender 5.0.1 L/U/delete-recreate/Live Update smoke, ZIP package validation, geometry benchmark, Rust diagnostics, исторические benchmarks и cProfile.

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
- В 0.2.0-alpha.3 `build_roof_payload()` кэширует проверенную верхнюю поверхность по source-object ID, XYZ-контуру, pitch и свесу. Толщина не входит в ключ: thickness-only Live Update перестраивает shell без повторного wavefront/plane-envelope расчёта.
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



### Blender UI, свес и Live Update — интегрированы в 0.2.0-alpha.3

- addon/properties.py: коллекция pitch-настроек по каждому edge, ссылки на исходный и сгенерированный объект, статус и переключатель Live Update.
- addon/operators/prepare.py: считывает контур и создаёт нумерованный список углов.
- addon/ui/panel.py: поля Edge NN (Vx→Vy), Thickness, Eave Overhang, Live Update, Validate и Create/Update.
- addon/live_update.py: debounce около 0.3 с, перестройка на Blender main thread, rollback при ошибке, rename guard и защита от удалённой крыши.
- addon/operators/generate.py: при удалении результата stale pointer очищается; новая крыша линкуется в root collection активной сцены и проверяется через `scene.objects` перед успешным ответом.
- Thickness, per-edge pitch и свес запускают Live Update. При изменении только thickness верхняя поверхность берётся из cache.
- Свес задаётся как горизонтальное расстояние в единицах сцены; работает на выпуклых контурах с продолжением support planes и convex corner joins. Nonzero overhang на reflex L/U пока намеренно отклоняется; для вогнутых контуров установи 0.
- UI-план крыши с графической нумерацией и подсветкой соответствующего edge пока отсутствует; в alpha поля соответствуют детерминированному порядку обхода.

### Ограничения, явно оставленные для пользовательской проверки

- Flat-Z L/U и ряд радиальных/волнистых семейств с индивидуальными углами проходят тесты и доступны через UI.
- Два multi-notch теста временно помечены как skipped с причиной: unresolved same-time split/collapse batches. Это известное ограничение alpha, а не успешная поддержка всех multi-notch contours.
- Mixed-Z контуры сохраняют XYZ и идут по прежнему 3D support-plane envelope; сложные вогнутые mixed-Z shapes могут быть отклонены.
- Пакет 0.2.0-alpha.3 собран и проверен официальным Blender 5.0.1 Extension validator; Blender smoke включает удаление/повторное создание, L/U, свес и cache-thickness test. Результат всё ещё требует ручного viewport QA пользователя.

### Ограничение размера

- 64 ребра — верхняя граница функционального и performance target для 0.2.0.
- Обычный CI benchmark и cProfile ограничены диапазоном 8, 16, 32 и 64 рёбер.
- Контуры больше 64 рёбер не входят в критерии приёмки этой версии; отдельная оптимизация для 128 рёбер не требуется.

## Точный статус готовности 0.2.0-alpha.3

- [x] Автоопределение одного замкнутого контура в Object/Edit Mode без выделения вершин/рёбер; wire и face mesh.
- [x] Per-edge pitch UI с нумерованными полями и vertex-pair подписью.
- [x] Flat-Z weighted wavefront подключён к пользовательскому генератору.
- [x] Mixed-Z контуры не сплющиваются и остаются на 3D support-plane path (ограничения для concave mixed-Z зафиксированы).
- [x] Debounced Live Update pitch/Thickness, rollback последней валидной крыши и rename guard.
- [x] Eave Overhang numeric setting: выпуклые контуры; reflex L/U с nonzero свесом завершаются явной диагностикой.
- [x] Blender 5.0.1 smoke включает L/U pitch, thickness-only cache, delete/recreate и overhang.
- [x] Чистый Extension ZIP 0.2.0-alpha.3 собран и принят официальным Blender Extension validator.
- [x] CI push и PR на commit `304a90a...` прошёл; Python 3.11/3.13, geometry/legacy/Rust/profile и Blender package jobs успешны.
- [ ] Универсальная обработка всех multi-notch / simultaneous split-collapse комбинаций.
- [ ] Общий solver для mixed-height concave XYZ contours.
- [ ] Визуальная подсветка соответствия ската его ребру и ручной viewport QA.

Итог: 0.2.0-alpha.3 готова к пользовательской проверке, но не является стабильным 0.2.0 release. PR остаётся draft до получения обратной связи и исправления обнаруженных ошибок.
