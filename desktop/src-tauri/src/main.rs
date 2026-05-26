fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("failed to run INTP Study Manager desktop shell");
}
