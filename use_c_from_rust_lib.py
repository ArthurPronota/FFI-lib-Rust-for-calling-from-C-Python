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
        raise FileNotFoundError(f"Library not found at {lib_path}. Please build the Rust library first.")

    return ctypes.CDLL(lib_path)


if __name__ == "__main__":
    rust_lib = load_ibrary_c_from_rust()
    rust_lib.add.argtypes = [ctypes.c_uint32, ctypes.c_uint32]  # Указываем the argument types for the add function
    rust_lib.add.restype = ctypes.c_int64

    left = 5
    right = 3
    result = rust_lib.add(left, right)
    if result >= 0: # успешное выполнение функции add
        print(f"Result of add({left}, {right}) from С library written in Rust : {result}") # Out: Result of add(5, 3) from С library written in Rust : 8
    else:   # ошибка выполнения функции add
        print(f"Error: The result of add({left}, {right}) is negative, which is unexpected.")
