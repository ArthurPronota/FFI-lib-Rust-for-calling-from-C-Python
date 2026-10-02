// отключает манглинг (искажение) имени функции.
#[unsafe(no_mangle)]
pub extern "C" fn add(left: u32, right: u32) -> i64 {
    // оборачиваем сложение в catch_unwind, чтобы перехватывать паники и возвращать -1 
    // в случае ошибки
    std::panic::catch_unwind(|| 
        left as i64 + right as i64
    )
    .unwrap_or(
        -1 as i64   // в случае ошибки возвращаем -1
    )
}
