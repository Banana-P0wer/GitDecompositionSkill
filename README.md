# git_decomposition_skill

`git_decomposition_skill` - это прототип для разборки одного git-коммита на логические части.

Идея простая: взять большой или смешанный commit, разложить его на атомарные элементы изменений, попросить несколько Codex-агентов посмотреть на эти элементы с разных сторон, а затем получить итоговую декомпозицию, человекочитаемый отчет и, когда это безопасно, patch-файлы по финальным группам.

Проект не пытается сам переписать историю git и не делает commit'ы. Он создает артефакты рядом с анализируемым репозиторием в `.git-dec/<commit_sha>/`.

## Как устроена архитектура

В проекте есть два слоя:

1. Детерминированный Python-слой.
2. Агентский слой Codex.

Python-слой отвечает за факты и безопасность:

- читает git commit;
- строит `input.json` с метаданными, файлами, hunks, line changes и analysis items;
- сохраняет исходный `diff.patch`;
- валидирует JSON, который написали агенты;
- пишет итоговые `report.md` и `report_items.md`;
- консервативно генерирует patch-файлы только из целых file sections diff'а;
- проверяет patch-файлы через `git apply --check` во временном worktree.

Агентский слой отвечает только за смысловую группировку:

- `explicit-agent` ищет прямые технические зависимости;
- `implicit-agent` ищет смысловые и контекстные связи;
- `reviewer-agent` сравнивает оба взгляда и принимает финальное решение.

Важно: LLM-агенты не пишут patch-файлы. Patch generation делает только Python.

## Основные части проекта

```text
main.py
src/
  prep.py
  validate_explicit.py
  validate_implicit.py
  validate_reviewer.py
  show_explicit.py
  show_implicit.py
  show_reviewer.py
  write_patches.py
  write_report.py
.agents/skills/git-dec/SKILL.md
.codex/agents/
  explicit-agent.toml
  implicit-agent.toml
  reviewer-agent.toml
references/
  explicit_agent.md
  explicit_agent_contract.md
  implicit_agent.md
  implicit_agent_contract.md
  reviewer_agent.md
  reviewer_agent_contract.md
```

`main.py` - главный вход для prepare stage. Он не запускает агентов сам, а только вызывает `src/prep.py`.

`src/prep.py` - строит машинное представление commit'а: `input.json` и `diff.patch`.

`src/validate_*.py` - проверяют, что agent JSON корректен, покрывает все `analysis_items` и не содержит лишних id.

`src/show_*.py` - печатают agent JSON в удобном виде для человека.

`src/write_patches.py` - строит безопасные patch-файлы по финальным reviewer-группам.

`src/write_report.py` - собирает итоговый Markdown-отчет.

`.agents/skills/git-dec/SKILL.md` - инструкция для Codex, как запускать весь workflow. Это оркестратор процесса.

`.codex/agents/*.toml` - описания custom subagents для Codex.

`references/*_contract.md` - контракты JSON-формата для агентских результатов.

## Как работает декомпозиция commit'а

### 1. Prepare stage

Codex запускает:

```bash
python3 main.py --repo <repo> --commit <commit>
```

`main.py` определяет настоящий commit hash, выбирает каталог вывода и вызывает `src/prep.py`.

Prepare stage читает git diff между parent commit и target commit. На выходе появляются:

```text
.git-dec/<hash>/input.json
.git-dec/<hash>/diff.patch
```

`input.json` содержит:

- репозиторий;
- target commit;
- parent commit;
- subject, author, date;
- список файлов;
- file events, например add, modify, rename;
- line changes с id вида `C000001`;
- file events с id вида `F000001`;
- общий список `analysis_items`.

Именно `analysis_items` дальше группируют агенты.

### 2. Explicit agent

`explicit-agent` группирует элементы по прямым техническим связям.

Например:

- одна строка меняет функцию, другая меняет ее вызов;
- один item переименовывает файл, другой обновляет путь;
- один item меняет структуру данных, другой меняет место использования.

Результат сохраняется в:

```text
.git-dec/<hash>/agents/explicit.json
```

После этого Python-валидатор проверяет, что все `analysis_items` использованы ровно один раз.

### 3. Implicit agent

`implicit-agent` смотрит шире. Он ищет не только прямые зависимости, но и общий смысл:

- одна задача разработки;
- один рефакторинг;
- похожая механическая правка в разных местах;
- документация и код, которые относятся к одной идее;
- перенос файлов и связанные обновления путей.

Результат сохраняется в:

```text
.git-dec/<hash>/agents/implicit.json
```

Он тоже проходит Python-валидацию.

### 4. Reviewer agent

`reviewer-agent` получает три входа:

- `input.json`;
- `agents/explicit.json`;
- `agents/implicit.json`.

Его задача - принять финальное решение:

- commit смешанный или нет;
- какие финальные группы существуют;
- почему элементы внутри каждой группы относятся друг к другу;
- где explicit и implicit взгляды расходились;
- насколько агент уверен в решении.

Результат сохраняется в:

```text
.git-dec/<hash>/agents/reviewer.json
```

Это главный agent output. Дальше Python уже строит вокруг него артефакты.

### 5. Patch stage

`src/write_patches.py` читает:

- `input.json`;
- `agents/reviewer.json`;
- `diff.patch`.

Он строит mapping `item_id -> reviewer_group_id`, разбирает `diff.patch` на file sections и действует консервативно:

- если весь diff file section относится к одной reviewer-группе, он попадает в patch этой группы;
- если один file section содержит items из нескольких групп, он считается unsafe;
- если section нельзя сопоставить с analysis items, он тоже считается unsafe.

Patch-файлы пишутся только для безопасных групп:

```text
.git-dec/<hash>/patches/R1.patch
.git-dec/<hash>/patches/R2.patch
.git-dec/<hash>/patches/patch_plan.json
```

`patch_plan.json` объясняет, что получилось:

- какие patch-файлы созданы;
- какие группы остались без patch;
- какие sections unsafe;
- прошла ли проверка `git apply --check`;
- можно ли считать все items patchable.

Проверка patch-файлов выполняется во временном worktree на parent commit. Основное рабочее дерево анализируемого репозитория не изменяется.

### 6. Report stage

`src/write_report.py` собирает два Markdown-файла:

```text
.git-dec/<hash>/report.md
.git-dec/<hash>/report_items.md
```

`report.md` - короткий отчет для чтения:

- metadata commit'а;
- verdict;
- финальные reviewer-группы;
- краткий sample items;
- summary explicit/implicit агентов;
- disagreements;
- patch files section;
- limitations.

`report_items.md` - полный список всех items по reviewer-группам. Он вынесен отдельно, чтобы основной отчет не превращался в стену из сотен строк.

## Как запускать в Codex

Основной сценарий - запускать skill из Codex:

```text
$git-dec
```

По умолчанию будет использован `HEAD` в текущем репозитории.

Можно явно указать commit:

```text
$git-dec HEAD~1
$git-dec <commit-hash>
$git-dec "часть commit subject"
```

Можно указать другой репозиторий:

```text
$git-dec --repo /path/to/repo --commit HEAD
```

Codex использует `.agents/skills/git-dec/SKILL.md` как workflow-инструкцию. Parent Codex запускает prepare stage, вызывает custom subagents, валидирует их JSON, затем запускает patch и report stages.

## Что получится на выходе

После полного запуска в анализируемом репозитории появится каталог:

```text
.git-dec/<commit_sha>/
```

Типичный результат:

```text
.git-dec/<commit_sha>/
  input.json
  diff.patch
  agents/
    explicit.json
    implicit.json
    reviewer.json
  patches/
    R1.patch
    R2.patch
    patch_plan.json
  report.md
  report_items.md
```

Если patch для какой-то группы нельзя безопасно построить, соответствующего `R*.patch` может не быть. Причина будет записана в `patches/patch_plan.json` и отражена в `report.md`.

## Примеры ручного запуска стадий

Обычно вручную это делать не нужно: Codex skill сам ведет workflow. Но для отладки удобно запускать стадии напрямую.

Подготовить commit:

```bash
python3 main.py --repo . --commit HEAD
```

Проверить reviewer output:

```bash
python3 src/validate_reviewer.py \
  --input .git-dec/<hash>/input.json \
  --explicit .git-dec/<hash>/agents/explicit.json \
  --implicit .git-dec/<hash>/agents/implicit.json \
  --reviewer .git-dec/<hash>/agents/reviewer.json
```

Сгенерировать patch-файлы:

```bash
python3 src/write_patches.py \
  --input .git-dec/<hash>/input.json \
  --reviewer .git-dec/<hash>/agents/reviewer.json \
  --diff .git-dec/<hash>/diff.patch \
  --out-dir .git-dec/<hash>/patches
```

Сгенерировать итоговый отчет:

```bash
python3 src/write_report.py \
  --input .git-dec/<hash>/input.json \
  --explicit .git-dec/<hash>/agents/explicit.json \
  --implicit .git-dec/<hash>/agents/implicit.json \
  --reviewer .git-dec/<hash>/agents/reviewer.json \
  --patch-plan .git-dec/<hash>/patches/patch_plan.json \
  --out .git-dec/<hash>/report.md \
  --items-out .git-dec/<hash>/report_items.md \
  --max-items-per-group 30
```

## Безопасность и ограничения

Проект намеренно осторожный:

- не меняет рабочее дерево анализируемого репозитория;
- не создает commit'ы;
- не запускает `git apply` в основном рабочем дереве;
- LLM-агенты не пишут patch-файлы;
- patch generation режет diff только по целым file sections;
- line-level и partial-hunk splitting пока не реализованы.

Это значит, что не каждый mixed commit можно автоматически разрезать на применимые patch-файлы. Зато если patch создан, он построен понятным и проверяемым способом.

## Как читать результат

Начинайте с:

```text
.git-dec/<hash>/report.md
```

Если нужен полный список строк и файловых событий, открывайте:

```text
.git-dec/<hash>/report_items.md
```

Если интересует, какие patch-файлы были созданы и что оказалось unsafe:

```text
.git-dec/<hash>/patches/patch_plan.json
```

Главный смысл результата находится в `reviewer.json` и `report.md`: там видно, считается ли commit смешанным, на какие группы он разложен и почему.
