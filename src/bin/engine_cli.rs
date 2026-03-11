use mini_data_systems::common::Row;
use mini_data_systems::product::{ConcurrentEngine, PersistentEngine};
use serde::Serialize;
use std::io::{self, BufRead, Write};
use std::env;

fn parse_i32(s: &str, name: &str) -> Result<i32, String> {
    s.parse::<i32>()
        .map_err(|e| format!("invalid {name} '{s}': {e}"))
}

fn print_usage() {
    println!("engine_cli usage:");
    println!("  cargo run --bin engine_cli -- init <root_dir> <table>");
    println!(
        "  cargo run --bin engine_cli -- insert <root_dir> <table> <order_id> <customer_id> <amount>"
    );
    println!(
        "  cargo run --bin engine_cli -- upsert <root_dir> <table> <order_id> <customer_id> <amount>"
    );
    println!("  cargo run --bin engine_cli -- index <root_dir> <table>");
    println!("  cargo run --bin engine_cli -- explain <root_dir> <table> <customer_id>");
    println!("  cargo run --bin engine_cli -- checkpoint <root_dir> <table>");
    println!("  cargo run --bin engine_cli -- tx-demo <root_dir> <table>");
    println!("  cargo run --bin engine_cli -- tx-recovery-list <root_dir> <table>");
    println!("  cargo run --bin engine_cli -- tx-recovery-commit <root_dir> <table> <tx_id>");
    println!("  cargo run --bin engine_cli -- tx-recovery-rollback <root_dir> <table> <tx_id>");
    println!("  cargo run --bin engine_cli -- serve <root_dir> <table>");
}

#[derive(Serialize)]
struct ServeResponse {
    ok: bool,
    returncode: i32,
    stdout: String,
    stderr: String,
    command: String,
    elapsed_ms: f64,
}

fn print_serve_response(resp: ServeResponse) {
    let line = serde_json::to_string(&resp).expect("serialize serve response");
    println!("{line}");
    io::stdout().flush().expect("flush serve response");
}

fn serve_ok(command: String, stdout: String, elapsed_ms: f64) {
    print_serve_response(ServeResponse {
        ok: true,
        returncode: 0,
        stdout,
        stderr: String::new(),
        command,
        elapsed_ms,
    });
}

fn serve_err(command: String, stderr: String, elapsed_ms: f64) {
    print_serve_response(ServeResponse {
        ok: false,
        returncode: 1,
        stdout: String::new(),
        stderr,
        command,
        elapsed_ms,
    });
}

fn run_serve(root: &str, table: &str) -> Result<(), String> {
    let mut engine = PersistentEngine::load_with_replay(root, table)?;
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = line.map_err(|e| format!("serve read failed: {e}"))?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if trimmed == "quit" {
            break;
        }

        let parts: Vec<&str> = trimmed.split_whitespace().collect();
        let command = parts[0].to_string();
        let started = std::time::Instant::now();

        match parts[0] {
            "insert" | "upsert" => {
                if parts.len() != 4 {
                    serve_err(
                        command,
                        "usage: insert|upsert <order_id> <customer_id> <amount>"
                            .to_string(),
                        started.elapsed().as_secs_f64() * 1000.0,
                    );
                    continue;
                }
                let parse_result = (|| -> Result<Row, String> {
                    Ok(Row {
                        order_id: parse_i32(parts[1], "order_id")?,
                        customer_id: parse_i32(parts[2], "customer_id")?,
                        amount: parse_i32(parts[3], "amount")?,
                        amount_with_tax: None,
                    })
                })();
                match parse_result {
                    Ok(row) => {
                        let result = if parts[0] == "insert" {
                            engine.insert(row)
                        } else {
                            engine.upsert_by_order_id(row)
                        };
                        match result {
                            Ok(_) => serve_ok(
                                command,
                                if parts[0] == "insert" {
                                    format!("inserted row into '{table}'")
                                } else {
                                    format!("upserted row in '{table}'")
                                },
                                started.elapsed().as_secs_f64() * 1000.0,
                            ),
                            Err(err) => serve_err(
                                command,
                                err,
                                started.elapsed().as_secs_f64() * 1000.0,
                            ),
                        }
                    }
                    Err(err) => serve_err(
                        command,
                        err,
                        started.elapsed().as_secs_f64() * 1000.0,
                    ),
                }
            }
            "index" => {
                engine.create_customer_index(64);
                serve_ok(
                    command,
                    format!("created customer_id index on '{table}'"),
                    started.elapsed().as_secs_f64() * 1000.0,
                );
            }
            "explain" => {
                if parts.len() != 2 {
                    serve_err(
                        command,
                        "usage: explain <customer_id>".to_string(),
                        started.elapsed().as_secs_f64() * 1000.0,
                    );
                    continue;
                }
                match parse_i32(parts[1], "customer_id") {
                    Ok(customer_id) => serve_ok(
                        command,
                        engine.explain_eq_customer(customer_id),
                        started.elapsed().as_secs_f64() * 1000.0,
                    ),
                    Err(err) => serve_err(
                        command,
                        err,
                        started.elapsed().as_secs_f64() * 1000.0,
                    ),
                }
            }
            "checkpoint" => match engine.checkpoint() {
                Ok(_) => serve_ok(
                    command,
                    format!("checkpointed '{table}' and truncated WAL"),
                    started.elapsed().as_secs_f64() * 1000.0,
                ),
                Err(err) => serve_err(
                    command,
                    err,
                    started.elapsed().as_secs_f64() * 1000.0,
                ),
            },
            _ => serve_err(
                command,
                format!("unsupported serve command: {}", parts[0]),
                started.elapsed().as_secs_f64() * 1000.0,
            ),
        }
    }
    Ok(())
}

fn main() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        print_usage();
        return Ok(());
    }

    match args[1].as_str() {
        "init" => {
            if args.len() != 4 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let _ = PersistentEngine::init(root, table)?;
            println!("initialized engine at '{}' table '{}'", root, table);
        }
        "insert" | "upsert" => {
            if args.len() != 7 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let order_id = parse_i32(&args[4], "order_id")?;
            let customer_id = parse_i32(&args[5], "customer_id")?;
            let amount = parse_i32(&args[6], "amount")?;

            let mut engine = PersistentEngine::load_with_replay(root, table)?;
            let row = Row {
                order_id,
                customer_id,
                amount,
                amount_with_tax: None,
            };
            if args[1] == "insert" {
                engine.insert(row)?;
                println!("inserted row into '{}'", table);
            } else {
                engine.upsert_by_order_id(row)?;
                println!("upserted row in '{}'", table);
            }
        }
        "index" => {
            if args.len() != 4 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let mut engine = PersistentEngine::load_with_replay(root, table)?;
            engine.create_customer_index(64);
            println!("created customer_id index on '{}'", table);
        }
        "explain" => {
            if args.len() != 5 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let customer_id = parse_i32(&args[4], "customer_id")?;
            let engine = PersistentEngine::load_with_replay(root, table)?;
            println!("{}", engine.explain_eq_customer(customer_id));
        }
        "checkpoint" => {
            if args.len() != 4 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let engine = PersistentEngine::load_with_replay(root, table)?;
            engine.checkpoint()?;
            println!("checkpointed '{}' and truncated WAL", table);
        }
        "tx-demo" => {
            if args.len() != 4 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let engine = PersistentEngine::load_with_replay(root, table)?;
            let concurrent = ConcurrentEngine::new(engine);

            let tx1 = concurrent.begin()?;
            let tx2 = concurrent.begin()?;
            println!("began tx1={}, tx2={}", tx1, tx2);
            println!("{}", concurrent.tx_read_snapshot_explain(tx1, 4242)?);

            concurrent.tx_upsert(
                tx1,
                Row {
                    order_id: 777,
                    customer_id: 4242,
                    amount: 10,
                    amount_with_tax: None,
                },
            )?;

            concurrent.commit(tx1)?;
            println!("committed tx1");

            concurrent.tx_upsert(
                tx2,
                Row {
                    order_id: 777,
                    customer_id: 1,
                    amount: 99,
                    amount_with_tax: None,
                },
            )?;
            match concurrent.commit(tx2) {
                Ok(_) => println!("committed tx2"),
                Err(e) => println!("tx2 conflict on commit: {e}"),
            }
        }
        "tx-recovery-list" => {
            if args.len() != 4 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let engine = PersistentEngine::load_with_replay(root, table)?;
            let concurrent = ConcurrentEngine::new(engine);
            let ids = concurrent.list_recovery_transactions()?;
            println!("recovery transactions: {:?}", ids);
        }
        "tx-recovery-commit" | "tx-recovery-rollback" => {
            if args.len() != 5 {
                print_usage();
                return Ok(());
            }
            let root = &args[2];
            let table = &args[3];
            let tx_id = args[4]
                .parse::<u64>()
                .map_err(|e| format!("invalid tx_id '{}': {e}", args[4]))?;
            let engine = PersistentEngine::load_with_replay(root, table)?;
            let concurrent = ConcurrentEngine::new(engine);
            if args[1] == "tx-recovery-commit" {
                concurrent.commit(tx_id)?;
                println!("recovery commit applied for tx_id={tx_id}");
            } else {
                concurrent.rollback(tx_id)?;
                println!("recovery rollback applied for tx_id={tx_id}");
            }
        }
        "serve" => {
            if args.len() != 4 {
                print_usage();
                return Ok(());
            }
            run_serve(&args[2], &args[3])?;
        }
        _ => {
            print_usage();
        }
    }

    Ok(())
}
