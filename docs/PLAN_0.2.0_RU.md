# RoofForge 0.2.0 — scope and implementation gates

**Working branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Base:** validated user-facing 0.1.0 alpha  
**Target:** Blender 5.0+  
**Status:** 0.2.0-alpha.11 implementation in progress; geometry/UI regression suite and package CI pending

## User-confirmed priorities

1. Support **simple** polygon contours with up to 64 boundary edges: convex, concave, narrow notches and non-uniform edge lengths. More than 64 edges are outside the 0.2.0 target; self-intersecting contours, zero-length projected edges and multiple independent boundary loops must be diagnosed, not silently repaired.
2. Do not require selecting vertices or edges in Edit Mode. Selecting the mesh object is enough; RoofForge discovers one outer boundary from the mesh topology. A face mesh uses its boundary edges; a wire-only mesh uses its closed wire loop.
3. Give every boundary edge/slope its own pitch angle. Use a compact list of numeric fields plus a numbered top-view roof-facet plan; each number is centered inside its generated slope and maps to the same ordered Pitch row.
4. Pitch edits trigger a debounced live rebuild. Keep the last valid roof visible until the replacement is built and validated. Coalesce rapid changes; never regenerate inside a UI draw callback.
5. Provide an optional eave overhang in centimeters by extending the source-edge pitch planes over one outward-offset domain. Keep the underside/support surface exactly on the original 3D contour; add shell thickness above that support surface. Reject collapsed or self-intersecting offsets.

Everything else in the 1.0 roadmap is deferred: ridge/valley/hip profiles, standing seams, UV, LOD, export, complex material handling and detach/relink.

## Geometry contract

- Calculations remain in source-object local coordinates and retain all XYZ boundary coordinates.
- Each source boundary edge owns one stable slope ID and one pitch angle. With overhang, its support plane remains anchored to the original edge endpoints; only the XY build domain is offset outward.
- Its plane must pass through both endpoint vertices and satisfy the requested total inclination. A mathematically incompatible pitch must fail with a clear message; never clamp it silently.
- The output must cover the source polygon exactly within scale-aware tolerances. Internal surface edges must be shared, and each boundary edge must be covered by the generated surface boundary.
- Output facets must retain source-slope identity and be planar. The final thickness shell must pass edge- and vertex-manifold validation. Coplanar internal seams must be dissolved from the Blender mesh.
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
- [ ] With nonzero convex overhang, the underside/support planes pass through every original contour edge and the shell is extruded upward from that support surface.
- [ ] Concave L/U contours still generate with zero overhang; nonzero overhang is rejected with a clear diagnostic.
- [ ] Coplanar internal roof edges are absent from the generated Blender mesh.
- [ ] The facet preview is transparent white RGBA, antialiased, width-responsive and labels stay inside their corresponding facet.
- [ ] Performance baselines exist at 8–64 edges, with 64 as the maximum 0.2.0 target; preview and final thresholds are defined from measured results.
- [x] Eaves use a single outward-offset source contour. Every new edge is parallel to its original edge and exactly the requested distance outward; corresponding vertex Z values and per-edge pitch order are preserved. The entire roof is rebuilt from this contour, with no post-build strips/caps. Convex and tested concave L/U contours, plus mixed-height convex XYZ, pass.
- [x] Live Update delay is adjustable from 0 to 1000 ms, default 0 ms; no intentional debounce at zero. Ridge/valley/hip, seam, UV, LOD or export controls remain out of scope.
- [x] Blender 5.0.1 background smoke and official extension package validation pass; manual viewport QA remains a separate gate.

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

### Собственный Python weighted wavefront (подключён в 0.2.0-alpha.10 для flat-Z контуров)

Versioned alpha.7 CI runs [42370549428](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42370549428) (push) and [42370553763](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42370553763) (PR) both passed on package commit `7730ac1b7b4caff1776c58a534cee04f40f34298`: Python 3.11/3.13, flat and concave offset-contour geometry tests, Blender 5.0.1 smoke, clean alpha.7 ZIP build, official Extension Validator, geometry/legacy/Rust/profile jobs.

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
- В 0.2.0-alpha.10 `build_roof_payload()` кэширует проверенную верхнюю поверхность по source-object ID, XYZ-контуру, pitch и свесу. Толщина не входит в ключ: thickness-only Live Update перестраивает shell без повторного wavefront/plane-envelope расчёта.
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



### Blender UI, сантиметры, свес и Live Update — интегрированы в 0.2.0-alpha.10

- addon/properties.py: коллекция pitch-настроек по каждому edge, ссылки на исходный и сгенерированный объект, статус и переключатель Live Update.
- addon/operators/prepare.py: считывает контур и создаёт нумерованный список углов.
- addon/ui/panel.py: нумерованный top-view план, автоматический масштаб по ширине N-панели, регулируемый размер цифр и напрямую редактируемые Pitch-поля. Thickness (cm), Eave Overhang (cm), Live Update, Update Delay и Create/Update; Default Pitch и Validate удалены.
- addon/live_update.py: настраиваемый debounce 0–1000 мс, по умолчанию 0 мс, перестройка на Blender main thread, rollback при ошибке, rename guard и защита от удалённой крыши.
- addon/operators/generate.py: при удалении результата stale pointer очищается; новая крыша линкуется в root collection активной сцены и проверяется через `scene.objects` перед успешным ответом.
- Thickness, per-edge pitch и свес запускают Live Update. При изменении только thickness верхняя поверхность берётся из cache.
- Свес и толщина задаются в сантиметрах. При ненулевом свесе исходный XY-контур смещается целиком: каждое ребро переносится наружу параллельно самому себе, а новая угловая вершина — пересечение двух соседних offset-линий.
- Сохраняется исходный Z соответствующей вершины и число/порядок рёбер. Благодаря этому список pitch остаётся привязан к тем же рёбрам.
- Roof solver запускается заново уже с новым контуром. Отдельные полосы, corner caps, ridge stitching и post-build геометрические заплатки не создаются.
- Вогнутые L/U-углы проходят тот же polygon offset; если паз схлопывается или новый контур пересекает сам себя, построение отклоняется до запуска solver.
- Схема сверху использует тот же deterministic boundary traversal: номер у ребра совпадает с номером Pitch-поля. PNG preview кэшируется по контуру и размеру цифр; draw callback не запускает roof solver. Постоянная цветная viewport overlay-подсветка остаётся отдельной задачей.

### Ограничения, явно оставленные для пользовательской проверки

- Flat-Z L/U и ряд радиальных/волнистых семейств с индивидуальными углами проходят тесты и доступны через UI.
- Два multi-notch теста временно помечены как skipped с причиной: unresolved same-time split/collapse batches. Это известное ограничение alpha, а не успешная поддержка всех multi-notch contours.
- Mixed-Z контуры сохраняют XYZ и идут по прежнему 3D support-plane envelope; сложные вогнутые mixed-Z shapes могут быть отклонены.
- Alpha.10 final CI passed on commit `d77b9907bb4b6c777e0ff890e8a07e81417cd1f2`: [push run](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42381677571) and [PR run](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42381682391). Both include Python 3.11/3.13, Blender 5.0.1 smoke, package build, official Extension Validator and all benchmark jobs.

### Ограничение размера

- 64 ребра — верхняя граница функционального и performance target для 0.2.0.
- Обычный CI benchmark и cProfile ограничены диапазоном 8, 16, 32 и 64 рёбер.
- Контуры больше 64 рёбер не входят в критерии приёмки этой версии; отдельная оптимизация для 128 рёбер не требуется.

## Аудит полезных решений из main / RoofForge 2.9.2

Проверен main commit `63d7952e0ee9c7aa62b4ed4efe40716a7641a2e0`, manifest `2.9.2` и монолитный UI/runtime.

**Перенесено в alpha.10:**
- Чертёжный top-view план с нумерацией рёбер.
- Совпадение номера на схеме с номером Pitch-поля.
- Автоматический масштаб схемы по ширине панели.
- Отдельная настройка размера цифр.
- Кэширование PNG preview и очистка preview/file при unregister.
- В отличие от 2.9.2, alpha.10 рисует номера прямо возле соответствующих рёбер исходного контура. Для этого не запускается roof solver из panel draw; используется сохранённый ordered contour.

**Другие полезные функции, найденные в 2.9.2, но пока не переносимые без адаптации:**
1. Ограничение частоты интерактивной пересборки (1–60 Hz) с отложенным финальным пересчётом профилей/деталей после завершения перетаскивания. Это может быть полезно на тяжёлых контурах, но нужно согласовать с текущим 0 ms debounce и не ухудшить отзывчивость.
2. Отдельные объекты коньков и ендов, извлекаемые из фактической топологии граней крыши. Их можно адаптировать к новой `RoofSurface` модели после проверки source-face metadata и 3D-кейсов.
3. Генератор standing-seam фальцевой раскладки с шириной панелей, высотой/шириной фальца и концевым смещением. В 2.9.2 spatial-режим имеет отдельные ограничения; алгоритм нужно подключать к текущим фасетам, не вызывая старый roof solver.
4. Сохранение исходной поверхности и параметров на generated object, чтобы обновлять профили после сохранения/открытия .blend. Это полезный архитектурный образец для последующей persistence/repair workflow.

**Не перенесено:** старый roof generation, старый weighted/spatial solver, старый overhang strip builder, старый thickness code и старый монолитный PropertyGroup. Они не совместимы напрямую с текущим solver/API и могут вернуть старые ограничения/дефекты.

## Точный статус готовности 0.2.0-alpha.10

- [x] Автоопределение одного замкнутого контура в Object/Edit Mode без выделения вершин/рёбер; wire и face mesh.
- [x] Per-edge pitch UI с нумерованными полями и vertex-pair подписью; новые поля default 30°.
- [x] Flat-Z weighted wavefront подключён к пользовательскому генератору.
- [x] Mixed-Z контуры сохраняют XYZ и используют 3D support-plane path.
- [x] Thickness по умолчанию 1 см; Eave Overhang и Thickness вводятся в сантиметрах с учётом Scene Unit Scale.
- [x] Validate Roof operator и Default Pitch property удалены; Create / Update выполняет валидацию.
- [x] Live Update с задержкой 0–1000 мс, default 0 мс, rollback last-valid roof и rename guard.
- [x] Single offset-contour eaves: flat variable-pitch convex, mixed-Z variable-pitch convex, concave L/U variable-pitch rebuild проходят Python/Blender smoke; self-intersect/collapsed offset отклоняется.
- [x] Blender 5.0.1 smoke: cm conversion, 30°/1 cm defaults, numbered top-view plan icon generation and label-size update, stored contour preview, flat/mixed-Z offset-contour rebuild, concave L/U offset-contour rebuild, oversized U offset rejection, cache and delete/recreate.
- [x] Clean Extension ZIP 0.2.0-alpha.10 собран и принят официальным Blender Extension Validator (artifact `13577397939`; inner ZIP SHA-256 `b08430a8454860226b469a6a7e23798771121fd376b6eb6efc69940ad77f6ca9`).
- [x] Edit Mode Show controls removed from the Pitch workflow. Per-edge pitch editing maps directly through the numbered top-view plan.
- [x] Pure renderer unit tests added for PNG signature/dimensions, monochrome output, configurable label size, double-digit edge labels, concave L/U contours and invalid inputs.
- [ ] Универсальная обработка всех multi-notch / simultaneous split-collapse комбинаций.
- [ ] Общий solver для mixed-height concave XYZ contours.
- [x] Alpha.10 push run `42381677571` and PR run `42381682391` passed all jobs: Python 3.11/3.13, Blender smoke, ZIP build, Extension Validator and all benchmark jobs.

Итог: 0.2.0-alpha.10 готова к ручной проверке в Blender. Pitch editing теперь не требует Edit Mode; связь полей с рёбрами показана на схеме.
