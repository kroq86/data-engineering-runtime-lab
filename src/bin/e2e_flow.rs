use mini_data_systems::common::{PlannerCosts, Row};
use mini_data_systems::pg::MiniPostgresLikeDb;
use mini_data_systems::product::PersistentEngine;
use std::path::PathBuf;
use std::process::Command;

fn main() -> Result<(), String> {
    println!("E2E Flow: MiniPG + MiniDatabricks + DuckDB\n");

    let root = PathBuf::from("./tests/artifacts/e2e/data");
    let table = "orders";

    // 1) MiniPG-like persistent write path (WAL + checkpoint).
    let mut engine = PersistentEngine::load_with_replay(&root, table)?;
    engine.insert(Row {
        order_id: 1,
        customer_id: 100,
        amount: 10,
        amount_with_tax: None,
    })?;
    engine.insert(Row {
        order_id: 2,
        customer_id: 4242,
        amount: 20,
        amount_with_tax: None,
    })?;
    engine.upsert_by_order_id(Row {
        order_id: 2,
        customer_id: 4242,
        amount: 25,
        amount_with_tax: None,
    })?;
    engine.create_customer_index(64);
    println!("MiniPG explain (before checkpoint):");
    println!("{}", engine.explain_eq_customer(4242));
    engine.checkpoint()?;
    println!("Checkpoint completed at {:?}", root.join("snapshot.csv"));

    // 2) MiniDatabricks-like bronze -> silver transform.
    let bronze_rows = engine.snapshot_rows();
    let silver_rows: Vec<Row> = bronze_rows
        .iter()
        .cloned()
        .map(|mut r| {
            r.amount_with_tax = Some((r.amount as f64) * 1.2);
            r
        })
        .collect();
    println!(
        "MiniDatabricks transform: bronze_rows={}, silver_rows={}",
        bronze_rows.len(),
        silver_rows.len()
    );

    // 3) MiniPostgres planner over transformed (silver) data.
    let mut planner_db = MiniPostgresLikeDb::new(PlannerCosts::default());
    planner_db.create_table("orders_silver");
    for row in &silver_rows {
        planner_db.insert_row("orders_silver", row.clone());
    }
    println!("MiniPG planner on silver (before index):");
    println!(
        "{}",
        planner_db.explain_analyze_eq("orders_silver", "customer_id", 4242)
    );
    planner_db.create_index("orders_silver", "customer_id", 64);
    println!("MiniPG planner on silver (after index):");
    println!(
        "{}",
        planner_db.explain_analyze_eq("orders_silver", "customer_id", 4242)
    );

    // 4) DuckDB validation directly on checkpoint snapshot.
    let snapshot_path = root.join("snapshot.csv");
    let sql = format!(
        "SELECT customer_id, COUNT(*) AS cnt, SUM(amount) AS total_amount \
         FROM read_csv_auto('{}', columns={{'order_id':'INTEGER','customer_id':'INTEGER','amount':'INTEGER'}}) \
         GROUP BY customer_id ORDER BY customer_id;",
        snapshot_path
            .to_string_lossy()
            .replace('\\', "\\\\")
            .replace('\'', "\\'")
    );

    let output = Command::new("duckdb")
        .arg("-noheader")
        .arg("-c")
        .arg(sql)
        .output()
        .map_err(|e| format!("failed to run duckdb: {e}"))?;

    if !output.status.success() {
        return Err(format!(
            "duckdb failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }

    println!("DuckDB validation over snapshot.csv (customer aggregates):");
    println!("{}", String::from_utf8_lossy(&output.stdout));

    println!(
        "E2E complete:\n\
         1) writes + WAL + checkpoint via PersistentEngine\n\
         2) bronze->silver transform\n\
         3) planner explain on silver\n\
         4) DuckDB SQL validation on persisted snapshot"
    );

    Ok(())
}
