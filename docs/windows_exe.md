# Windows exe

`dist/AvalancheView.exe` — переносимый Windows x64 exe. Внутри находятся Python, PyQt6/Qt WebEngine, библиотеки чтения NetCDF/GIS и локальные ресурсы MapLibre/deck.gl. Python и `.venv` на машине запуска не требуются.

Запуск: двойной щелчок по exe, затем «Файл → Открыть». Также можно передать файл/папку модели в командной строке или открыть синтетическую демонстрацию:

```powershell
.\AvalancheView.exe "C:\Models\wrfout_d01_2025-02-18_12%3A00%3A00"
.\AvalancheView.exe --demo
```

Логи, синтетическая демонстрация и Cartopy-кэш exe хранятся в `%LOCALAPPDATA%\AvalancheView`; логи — в подпапке `logs`. Пользовательские настройки интерфейса сохраняются прежним механизмом QSettings. Встроенные ресурсы читаются из пакета; для постоянных данных используется отдельный пользовательский каталог, поскольку onefile распаковывается во временную папку. Переменная `AVALANCHEVIEW_DATA_DIR` позволяет задать другой каталог данных.

## Повторная сборка

Из корня проекта:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\tools\build_windows.ps1
```

По умолчанию создаётся один exe в `dist`. Для версии с файлами рядом:

```powershell
.\tools\build_windows.ps1 -Mode onedir
```

Тогда требуется переносить **всю** папку `dist/AvalancheView`, а не только exe из неё. Два режима могут использовать общий кэш `build/pyinstaller`; логи сборки находятся в `build/logs/`. Параметр `-WorkPath` позволяет выбрать другой кэш.

`AvalancheView.spec` задаёт ресурсы, динамические xarray backends, метаданные пакетов и QtAgg/Agg. Штатные hooks PyInstaller собирают QtWebEngineProcess, Qt plugins/resources, нативные библиотеки NetCDF/HDF5, PROJ и GDAL. `tools/make_windows_icon.py` преобразует существующий SVG приложения в ICO. Используются PyInstaller 6.22.3 и hooks-contrib 2026.8.

Описание механизма: [PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html), [spec files](https://pyinstaller.org/en/stable/spec-files.html).

## Проверка exe

```powershell
.\.venv\Scripts\python.exe tools/verify_exe.py dist/AvalancheView.exe --output verification/frozen/onefile-demo
.\.venv\Scripts\python.exe tools/verify_exe.py dist/AvalancheView.exe --file verification/snowpack/synthetic_wrfout.nc --output verification/frozen/onefile-snowpack
```

Проверка запускает **сам exe** из другой рабочей папки с Python/.venv, убранными из PATH и переменных поиска модулей. Приложение открывает данные, получает реальный WebGL-кадр и экспортирует PNG. Для Snowpack дополнительно проверяет чтение профилей. Настройки проверки записываются в отдельный ini, подложка отключена, используется модельный рельеф. Проверка не требует сетевых тайлов и не изменяет рабочие настройки пользователя.

`--smoke-test --smoke-report PATH` создаёт JSON-отчёт и снимки окна/карты. Ошибка или таймаут возвращают ненулевой код завершения. Успех требует фактического рендера и экспорта, а не только появления процесса.

## Результаты текущей сборки

Сборка выполнена 7 октября 2026 года на Windows 11 x64, Python 3.13.12.

- Готовый файл: `dist/AvalancheView.exe`, **347 672 926 байт** (около 348 MB / 332 MiB).
- SHA-256: `1132aff99a3cd26ed70e01ad625e63c7dfeb98c03e64a096e16b057fd0d8faad`; также сохранён в `dist/AvalancheView.sha256`.
- **117 тестов прошли**, включая проверки постоянных путей frozen-приложения. Сохранилось известное upstream-предупреждение netCDF4/Cython в тесте повреждённого файла.
- `ruff check .`: passed; `pip check`: No broken requirements found.
- Оба варианта exe (onedir и onefile) прошли автономный запуск с очищенным Python PATH: демоданные, Snowpack NetCDF4, Snowpack NetCDF3 Classic и реальный met_em. Все запуски получили WebGL-кадр и экспортировали PNG. Snowpack вернул `[0, 4, 5]` активных элементов.
- JSON-отчёты, снимки окна/карты и изолированные настройки находятся в `verification/frozen/`; сводка сборки — `dist/AvalancheView.build.json`.

Сборщик выдаёт предупреждения о `snappy.dll` и `zlib.dll`, зависимостях `netCDF4.libs/blosc.dll`. Проверенные NetCDF3/4 и met_em работают; файлы со сторонними Blosc/Snappy-фильтрами отдельно не проверялись. Полный журнал — `build/logs/onefile.log`.
