use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn unique_temp_path(name: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before epoch")
        .as_nanos();
    std::env::temp_dir().join(format!("mini_data_systems_{name}_{nanos}"))
}

#[test]
fn engine_cli_init_insert_and_explain_round_trip() {
    let bin = env!("CARGO_BIN_EXE_engine_cli");
    let root = unique_temp_path("engine_cli_round_trip");

    let init = Command::new(bin)
        .args(["init", root.to_str().unwrap(), "orders"])
        .output()
        .expect("run init");
    assert!(init.status.success(), "init stderr: {}", String::from_utf8_lossy(&init.stderr));

    let insert = Command::new(bin)
        .args(["insert", root.to_str().unwrap(), "orders", "1", "4242", "10"])
        .output()
        .expect("run insert");
    assert!(insert.status.success(), "insert stderr: {}", String::from_utf8_lossy(&insert.stderr));

    let explain = Command::new(bin)
        .args(["explain", root.to_str().unwrap(), "orders", "4242"])
        .output()
        .expect("run explain");
    assert!(explain.status.success(), "explain stderr: {}", String::from_utf8_lossy(&explain.stderr));
    let stdout = String::from_utf8_lossy(&explain.stdout);
    assert!(stdout.contains("EXPLAIN ANALYZE"));
    assert!(stdout.contains("Actual Rows: 1"));

    let _ = fs::remove_dir_all(root);
}

#[test]
fn engine_cli_init_fails_when_root_is_a_file() {
    let bin = env!("CARGO_BIN_EXE_engine_cli");
    let root = unique_temp_path("engine_cli_bad_root");
    fs::write(&root, "blocked").expect("write blocker file");

    let init = Command::new(bin)
        .args(["init", root.to_str().unwrap(), "orders"])
        .output()
        .expect("run init");
    assert!(!init.status.success());
    let stderr = String::from_utf8_lossy(&init.stderr);
    assert!(stderr.contains("create_dir_all failed"));

    let _ = fs::remove_file(root);
}
