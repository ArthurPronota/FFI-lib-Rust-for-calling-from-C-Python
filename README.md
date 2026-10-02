# Создание FFI-библиотеки на Rust для вызова из C/Python

У вас получился **образцовый пример** экспорта Rust-функции в C ABI с защитой от паник. Разберём всё по порядку: от `#[unsafe(no_mangle)]` до запуска из Python.

---

## Структура проекта

```
o_069/
├── Cargo.toml
├── src/
│   └── lib.rs
└── use_c_from_rust_lib.py
```

**`Cargo.toml`:**

```toml
[package]
name = "o_069"
version = "0.1.0"
edition = "2024"

[dependencies]
libc = "0.2.189"

[lib]
name = "add_c_from_rust"
crate-type = ["cdylib"]
```

---

## Ключевые элементы `Cargo.toml`

### `crate-type = ["cdylib"]`

Определяет **тип артефакта**, который производит Cargo.

| Тип | Что создаёт | Для чего |
|---|---|---|
| `lib` (по умолчанию) | `libX.rlib` | Rust-библиотека для Rust |
| `rlib` | `.rlib` | явно Rust-библиотека |
| `dylib` | `.so`/`.dll`/`.dylib` | динамическая Rust-библиотека (для Rust) |
| **`cdylib`** | `.so`/`.dll`/`.dylib` | **C-совместимая динамическая библиотека** |
| `staticlib` | `.a`/`.lib` | C-совместимая статическая библиотека |
| `bin` | исполняемый файл | приложение |

**`cdylib`** = **C dynamic library**. Именно этот тип даёт:
- C ABI-совместимые символы;
- без экспорта внутренних Rust-символов (мономорфизации, метаданных);
- компактный бинарник, пригодный для `dlopen`/`LoadLibrary`/`ctypes.CDLL`.

Без `cdylib` Python не смог бы загрузить библиотеку — там были бы Rust-специфичные символы.

### `[lib] name = "add_c_from_rust"`

Задаёт **имя итогового файла**. Cargo добавит префикс/суффикс по платформе:

| Платформа | Файл |
|---|---|
| Windows | `add_c_from_rust.dll` |
| Linux | `libadd_c_from_rust.so` |
| macOS | `libadd_c_from_rust.dylib` |

Без `[lib] name` файл назывался бы по имени пакета (`o_069`), что неудобно.

### `libc = "0.2.189"`

В данном примере **не используется** — можно удалить. `libc` нужен, когда вы работаете с типами C (`c_int`, `c_char`, `size_t` и т.п.) или вызываете функции из C. Здесь всё обходится примитивами Rust (`u32`, `i64`), которые FFI-safe.

---

## Ключевые элементы `lib.rs`

### 1. `#[unsafe(no_mangle)]`

Отключает **манглинг** (name mangling) — искажение имён компилятором.

По умолчанию Rust превращает:

```rust
pub extern "C" fn add(...)  // в коде
```

в что-то вроде:

```
_ZN4o_0693add17h1234567890abcdefE  // в бинарнике
```

Это нужно для:
- уникальности имён при композиции;
- поддержки перегрузки, generics, модулей.

Но из C/Python вы ожидаете **просто `add`**. `#[no_mangle]` говорит компилятору: «не переименовывай — экспортируй символ ровно с этим именем».

```rust
#[unsafe(no_mangle)]
pub extern "C" fn add(...)  // символ в бинарнике: "add"
```

**Почему `#[unsafe(no_mangle)]`, а не `#[no_mangle]`?**

В edition 2024 атрибут `no_mangle` требует обёртки `unsafe(...)`, потому что экспорт символа с фиксированным именем может конфликтовать с другими символами (в том числе из C-библиотек) — это потенциально опасно. Раньше писали просто `#[no_mangle]`; теперь — `#[unsafe(no_mangle)]`.

### 2. `pub extern "C" fn`

| Часть | Значение |
|---|---|
| `pub` | символ виден снаружи (для `cdylib` обязателен) |
| `extern "C"` | **C ABI** — соглашение о вызовах |
| `fn add(...)` | имя функции |

**ABI (Application Binary Interface)** определяет:
- как передаются аргументы (регистры / стек, порядок);
- как возвращается значение;
- кто чистит стек;
- выравнивание;
- обработку ошибок.

`extern "C"` = `extern "cdecl"` на x86, стандартное соглашение для C на всех платформах.

Без `extern "C"` Rust использует **свой** ABI, который:
- не документирован;
- может меняться между версиями;
- не совместим с C.

Такую функцию Python вызвать **не смог бы**.

### 3. Типы аргументов и возврата

```rust
fn add(left: u32, right: u32) -> i64
```

Маппинг на C:

| Rust | C | Python ctypes |
|---|---|---|
| `u32` | `uint32_t` | `c_uint32` |
| `i64` | `int64_t` | `c_int64` |

Почему `i64`, а не `u32`? Потому что `-1` (код ошибки) должен помещаться в результат. Если бы возвращали `u32`, `-1` стал бы `4294967295` и проверка `result >= 0` в Python не сработала бы.

### 4. `catch_unwind` — защита от паник

```rust
std::panic::catch_unwind(|| 
    left as i64 + right as i64
)
.unwrap_or(-1 as i64)
```

**Зачем:**

Паника (panic) в Rust — это механизм аварийного завершения. Она **разворачивает стек** (unwinding), вызывая деструкторы.

Когда паника пересекает границу FFI (`extern "C"`), происходит **UB (undefined behavior)**, потому что:
- C-код не знает о механизме паник Rust;
- unwinding в C — это неопределённое поведение;
- на стороне C нет обработчиков.

**`catch_unwind`** перехватывает панику **до** того, как она пересечёт границу:

```rust
std::panic::catch_unwind(|| { /* код */ })  // → Result<T, Box<dyn Any>>
    .unwrap_or(-1)                            // если паника → -1
```

**Возвращаемый тип:** `Result<i64, Box<dyn Any + Send>>`. `.unwrap_or(-1)` даёт `i64` в любом случае.

**Соглашение:** отрицательные значения = ошибка. В C это распространённый паттерн (errno, `-1` для `read`, `write`, `close`).

### Почему это всё ещё может «паниковать» в edition 2024

В edition 2021+ (и особенно 2024) поведение по умолчанию для `extern "C"` — **abort при панике**, а не unwinding. То есть компилятор **сам** вставит `abort()`, если паника попытается пересечь FFI-границу.

Это значит:
- **UB больше нет** — процесс просто аварийно завершается;
- но **приложение падает**, а не возвращает ошибку.

Поэтому `catch_unwind` **всё ещё нужен**, если хотите обработать панику и вернуть код ошибки, а не рушить процесс.

```rust
// без catch_unwind: паника → abort → крах Python-процесса
// с catch_unwind: паника → -1 → Python продолжает работу
```

---

## Полный разбор `lib.rs`

```rust
#[unsafe(no_mangle)]
pub extern "C" fn add(left: u32, right: u32) -> i64 {
    std::panic::catch_unwind(|| 
        left as i64 + right as i64
    )
    .unwrap_or(-1 as i64)
}
```

Что происходит:

1. `#[unsafe(no_mangle)]` — символ экспортируется как `add`.
2. `pub extern "C"` — C ABI, функция видна снаружи.
3. `catch_unwind(|| ...)` — выполняет замыкание, ловит панику.
4. `left as i64 + right as i64` — приведение к `i64` **до** сложения, чтобы избежать переполнения `u32`.
5. `.unwrap_or(-1)` — если паника, вернуть `-1`.

**Важный момент:** приведение `as i64` **до** `+` критично. Если написать:

```rust
left + right  // ❌ может переполнить u32 → паника в debug
```

то при `left = u32::MAX, right = 1` в debug-сборке будет паника, в release — wrap-around. Правильно:

```rust
left as i64 + right as i64  // ✅ вмещается в i64
```

---

## Разбор Python-скрипта

### 1. Загрузка библиотеки

```python
import ctypes
import os
import platform

def load_ibrary_c_from_rust():
    system = platform.system()
    if system == "Windows":
        lib_path = "target/release/add_c_from_rust.dll"
    elif system == "Linux":
        lib_path = "target/release/libadd_c_from_rust.so"
    elif system == "Darwin":
        lib_path = "target/release/libadd_c_from_rust.dylib"
    else:
        raise Exception(f"Unsupported platform: {system}")

    if not os.path.exists(lib_path):
        raise FileNotFoundError(...)

    return ctypes.CDLL(lib_path)
```

- `platform.system()` — определяет ОС.
- Путь к библиотеке зависит от платформы (префикс `lib` и расширение).
- `ctypes.CDLL` — загружает `.dll`/`.so`/`.dylib` в процесс Python.

### 2. Настройка сигнатуры

```python
rust_lib.add.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
rust_lib.add.restype = ctypes.c_int64
```

**Это критично.** Без указания типов `ctypes` по умолчанию:
- считает аргументы `int` (C `int`, 32 бита);
- возвращает `int` (C `int`, 32 бита).

Для `u32`/`i64` это может дать **неправильный результат** или **краш** (несовпадение размеров).

| ctypes | C | Rust |
|---|---|---|
| `c_uint32` | `uint32_t` | `u32` |
| `c_int64` | `int64_t` | `i64` |
| `c_int` | `int` | `i32` (обычно) |
| `c_char_p` | `char*` | `*const c_char` |
| `c_void_p` | `void*` | `*mut c_void` |

### 3. Вызов

```python
result = rust_lib.add(left, right)
if result >= 0:
    print(f"... {result}")
else:
    print(f"Error: ...")
```

Python вызывает `add` через C ABI. Если Rust вернул `-1` (паника поймана), Python видит отрицательное число.

### 4. Опечатки в коде

```python
def load_ibrary_c_from_rust():   # ← пропущена "l" в "library"
    ...
lib_path = "target/release/add_c_from_rust.dll"
rust_lib = load_ibrary_c_from_rust()  # ← та же опечатка
```

Работает, но лучше переименовать в `load_library_c_from_rust`.

Также `os.path.exists` использует **относительный путь** — скрипт нужно запускать **из корня проекта** (`o_069/`), иначе `target/release/...` не найдётся.

---

## Пошаговая сборка и запуск

```bash
# 1. Создать проект
cargo new o_069 --lib
cd o_069

# 2. (Отредактировать Cargo.toml и src/lib.rs)

# 3. Собрать release-версию
cargo build --release

# 4. Проверить, что символ экспортирован (Linux/macOS)
nm -D target/release/libadd_c_from_rust.so | grep add
# или
objdump -T target/release/libadd_c_from_rust.so | grep add
```

Ожидаемый вывод: `... T add` — символ `add` в секции `.text`.

На Windows:

```powershell
dumpbin /exports target\release\add_c_from_rust.dll | findstr add
```

### Запуск

```bash
python use_c_from_rust_lib.py
```

Вывод:
```
Result of add(5, 3) from С library written in Rust : 8
```

---

## Глубокое погружение: ABI и calling conventions

### Что определяет ABI

| Аспект | Пример |
|---|---|
| Порядок аргументов | слева направо |
| Способ передачи | регистры, затем стек |
| Кто чистит стек | вызывающий (cdecl) |
| Возврат значения | `rax`/`eax` для целых |
| Выравнивание | 16 байт на x86-64 |
| Имена символов | C: без манглинга, Rust: mangled |
| Обработка исключений | C — нет, C++ — есть, Rust — panic/unwind |

### Соглашения о вызовах

| Соглашение | Платформа | Особенности |
|---|---|---|
| `cdecl` | x86 | вызывающий чистит стек |
| `stdcall` | Windows x86 | вызываемый чистит стек |
| `fastcall` | Windows x86 | аргументы в регистрах |
| **`sysv64`** | Linux/macOS x86-64 | System V AMD64 ABI |
| **`win64`** | Windows x64 | Microsoft x64 ABI |
| `aapcs` | ARM | ARM ABI |

В Rust:

```rust
extern "C" fn f() {}         // C ABI (cdecl на x86, sysv64/win64 на x64)
extern "sysv64" fn g() {}    // System V AMD64
extern "win64" fn h() {}     // Microsoft x64
extern "stdcall" fn i() {}   // stdcall
extern "Rust" fn j() {}      // Rust ABI (по умолчанию)
```

`extern "C"` — **самый переносимый** вариант. Работает на всех платформах, понятен всем языкам.

---

## Паника через границу FFI — детали

### Что было раньше (до edition 2021)

Panic в `extern "C"` → **unwinding через C-код** → **UB**.

На практике:
- C-код не знал об unwinding;
- деструкторы на стороне C не вызывались;
- поведение зависело от компилятора и фазы луны.

### Что стало (edition 2021+)

Компилятор **автоматически** вставляет `abort` при попытке паники пересечь `extern "C"`:

```rust
extern "C" fn f() {
    panic!("boom"); // → abort() — процесс немедленно завершается
}
```

Это уже **не UB**, но **процесс падает**. Для библиотеки, вызываемой из Python, это означает крах Python-интерпретатора.

### `catch_unwind` — правильное решение

```rust
#[unsafe(no_mangle)]
pub extern "C" fn add(left: u32, right: u32) -> i64 {
    std::panic::catch_unwind(|| {
        left as i64 + right as i64
    }).unwrap_or(-1)
}
```

Паника **ловится внутри Rust**, процесс не падает, наружу возвращается код ошибки.

### Что `catch_unwind` **не** ловит

- `std::process::abort()` — это не паника;
- `panic = "abort"` в `Cargo.toml` — тогда `catch_unwind` **не работает** (нет unwinding);
- панику в **другом потоке** — она не пересекает ваш `catch_unwind`;
- `SIGSEGV`, `SIGABRT`, аппаратные исключения.

### `panic = "abort"` в профиле

```toml
[profile.release]
panic = "abort"
```

С этой опцией:
- бинарник меньше и быстрее;
- но `catch_unwind` **бесполезен** — паника сразу завершает процесс;
- для FFI-библиотек обычно **не используют** `panic = "abort"`, если хотят возвращать ошибки.

---

## Почему `-1` — хороший код ошибки

В C-мире соглашение: функции возвращают **неотрицательные значения** при успехе и **`-1`** при ошибке (а детали — в `errno`).

```c
ssize_t read(int fd, void *buf, size_t count);
// возвращает: >= 0 — сколько прочитано; -1 — ошибка
```

Ваш `add` следует тому же паттерну. Python проверяет `result >= 0`.

**Ограничение:** если `add` может вернуть `-1` **легально** (например, `left = 0, right = -1` — но у нас `u32`, отрицательных нет), то соглашение ломается. Для `u32 + u32` результат всегда `>= 0`, так что `-1` однозначно означает ошибку. Для знаковых операций нужен **отдельный out-параметр** или другой код ошибки.

---

## Улучшения примера

### 1. Убрать неиспользуемую зависимость

```toml
[dependencies]
# libc = "0.2.189"  ← не нужен
```

### 2. Использовать `wrapping_add` вместо `as i64`

Если хотите именно `u32`-арифметику с обёрткой:

```rust
pub extern "C" fn add(left: u32, right: u32) -> i64 {
    std::panic::catch_unwind(|| {
        left.wrapping_add(right) as i64
    }).unwrap_or(-1)
}
```

Но тогда переполнение не паникует и не даёт ошибку — просто оборачивается.

### 3. Явные типы C

Для сложных сигнатур используйте `libc` или `core::ffi`:

```rust
use core::ffi::{c_int, c_uint};

pub extern "C" fn add(left: c_uint, right: c_uint) -> c_int {
    // ...
}
```

### 4. Логирование ошибки

```rust
pub extern "C" fn add(left: u32, right: u32) -> i64 {
    match std::panic::catch_unwind(|| left as i64 + right as i64) {
        Ok(v) => v,
        Err(_) => {
            eprintln!("panic in add({left}, {right})");
            -1
        }
    }
}
```

### 5. Статическая библиотека вместо динамической

```toml
crate-type = ["staticlib", "cdylib"]
```

`.a`/`.lib` для линковки в C-приложение, `.so`/`.dll` — для загрузки в runtime.

### 6. Проверка на Python

```python
import ctypes

rust_lib = ctypes.CDLL("./target/release/libadd_c_from_rust.so")
rust_lib.add.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
rust_lib.add.restype = ctypes.c_int64

# тест: переполнение i64 невозможно для u32 + u32
print(rust_lib.add(2**32 - 1, 2**32 - 1))  # 8589934590
```

---

## Частые ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `undefined symbol: add` | забыли `#[no_mangle]` | добавить `#[unsafe(no_mangle)]` |
| `cannot find -ladd_c_from_rust` | нет `crate-type = ["cdylib"]` | добавить в `[lib]` |
| Python: `OSError: ... invalid ELF header` | загрузили `.rlib` вместо `.so` | пересобрать с `cdylib` |
| Неверный результат | не заданы `argtypes`/`restype` | задать явно |
| `abort` при вызове | паника без `catch_unwind` | обернуть в `catch_unwind` |
| `catch_unwind` не помогает | `panic = "abort"` в профиле | убрать или использовать unwind |
| Крах Python | паника пересекла FFI | `catch_unwind` + возврат кода ошибки |

---

## Итоговая схема

```
┌──────────────────────┐
│  Rust (lib.rs)       │
│  #[unsafe(no_mangle)]│  ← символ "add" без манглинга
│  extern "C" fn add   │  ← C ABI
│  catch_unwind(...)   │  ← защита от паники
│  → i64               │  ← -1 = ошибка
└──────────┬───────────┘
           │ cargo build --release
           ▼
┌──────────────────────┐
│  cdylib              │
│  libadd_c_from_rust  │
│  .so / .dll / .dylib │
└──────────┬───────────┘
           │ ctypes.CDLL
           ▼
┌──────────────────────┐
│  Python              │
│  argtypes = [u32,u32]│
│  restype  = i64      │
│  add(5, 3) → 8       │
└──────────────────────┘
```

---

## Итог

| Элемент | Роль |
|---|---|
| `crate-type = ["cdylib"]` | C-совместимая динамическая библиотека |
| `[lib] name = ...` | имя итогового файла |
| `#[unsafe(no_mangle)]` | не искажать имя символа |
| `pub extern "C" fn` | C ABI, экспорт символа |
| `u32`, `i64` | FFI-safe примитивы |
| `catch_unwind` | ловить панику до границы FFI |
| `.unwrap_or(-1)` | код ошибки вместо паники |
| `ctypes.CDLL` | загрузка библиотеки из Python |
| `argtypes`/`restype` | точная сигнатура для C ABI |
| `-1` | соглашение C об ошибке |

**Главная идея:** Rust может производить **C-совместимые библиотеки**, которые вызываются из C/C++/Python и других языков. Ключевые требования: `cdylib`, `#[unsafe(no_mangle)]`, `extern "C"`, FFI-safe типы и **обязательная защита от паник** через `catch_unwind`. В edition 2024 паника через FFI-границу приводит к `abort`, а не к UB, но `catch_unwind` всё равно нужен, чтобы вернуть код ошибки, а не рушить процесс вызывающей стороны.
