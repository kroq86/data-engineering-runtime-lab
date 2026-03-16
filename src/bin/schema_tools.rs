//! CLI for schema tools: DDL normalization and EXPLAIN plan parsing.
//! Invoked by Python schema_ddl and schema_evaluate when binary is available.

use mini_data_systems::schema::{ddl_to_duckdb, parse_duckdb_plan};
use serde::Serialize;
use std::io::{self, Read, Write};
use std::process;

#[derive(Serialize)]
struct ParsePlanOut {
    time_ms: Option<f64>,
    plan_summary: String,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let sub = args.get(1).map(String::as_str).unwrap_or("");
    let mut stdin = io::stdin();
    let mut input = String::new();
    if stdin.read_to_string(&mut input).is_err() {
        eprintln!("schema_tools: failed to read stdin");
        process::exit(1);
    }
    let input = input.trim_end_matches('\n').trim_end_matches('\r');

    match sub {
        "normalize-ddl" => {
            let out = ddl_to_duckdb(input);
            if io::stdout().write_all(out.as_bytes()).is_err() {
                process::exit(1);
            }
        }
        "parse-plan" => {
            let (time_ms, plan_summary) = parse_duckdb_plan(input);
            let out = ParsePlanOut {
                time_ms,
                plan_summary,
            };
            if let Ok(json) = serde_json::to_string(&out) {
                if io::stdout().write_all(json.as_bytes()).is_err() {
                    process::exit(1);
                }
            } else {
                process::exit(1);
            }
        }
        _ => {
            eprintln!("schema_tools usage:");
            eprintln!("  normalize-ddl   stdin: DDL text  → stdout: normalized DDL");
            eprintln!("  parse-plan      stdin: EXPLAIN text → stdout: JSON {{ time_ms, plan_summary }}");
            process::exit(1);
        }
    }
}
