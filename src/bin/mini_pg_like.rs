use mini_data_systems::common::{CommandEvent, EventLog, PlannerCosts, Row, stable_hash};
use mini_data_systems::pg::MiniPostgresLikeDb;
use std::collections::HashMap;
use std::time::Instant;

#[derive(Clone, Debug)]
struct InsertPayload {
    table: String,
    rows: Vec<Row>,
}

#[derive(Clone, Debug)]
struct InsertCommand {
    run_id: String,
    source: String,
    scope: String,
    idempotency_key: String,
    payload: InsertPayload,
}

#[derive(Clone, Debug)]
struct InsertResult {
    inserted: usize,
}

struct InsertAdapter;

impl InsertAdapter {
    fn validate(db: &MiniPostgresLikeDb, payload: &InsertPayload) -> Result<(), String> {
        if payload.rows.is_empty() {
            return Err("rows must be non-empty".to_string());
        }
        if !db.tables.contains_key(&payload.table) {
            return Err("table does not exist".to_string());
        }
        Ok(())
    }

    fn run(db: &mut MiniPostgresLikeDb, payload: &InsertPayload) -> InsertResult {
        for row in &payload.rows {
            db.insert_row(&payload.table, row.clone());
        }
        InsertResult {
            inserted: payload.rows.len(),
        }
    }
}

struct WriteCore {
    idempotency_store: HashMap<String, InsertResult>,
}

impl WriteCore {
    fn new() -> Self {
        Self {
            idempotency_store: HashMap::new(),
        }
    }

    fn execute(
        &mut self,
        db: &mut MiniPostgresLikeDb,
        events: &mut EventLog,
        cmd: &InsertCommand,
    ) -> Result<InsertResult, String> {
        let started = Instant::now();
        let payload_hash = stable_hash(&format!("{:?}", cmd.payload));
        let identity = format!("{}:{}:{}", cmd.scope, cmd.idempotency_key, payload_hash);
        events.emit(CommandEvent {
            event_type: "command.start".to_string(),
            run_id: cmd.run_id.clone(),
            source: cmd.source.clone(),
            idempotency_key: cmd.idempotency_key.clone(),
            payload_hash,
            attempt: 1,
            latency_ms: 0.0,
            scope: cmd.scope.clone(),
            details: format!("table={}", cmd.payload.table),
        });

        if let Some(existing) = self.idempotency_store.get(&identity) {
            events.emit(CommandEvent {
                event_type: "command.success".to_string(),
                run_id: cmd.run_id.clone(),
                source: cmd.source.clone(),
                idempotency_key: cmd.idempotency_key.clone(),
                payload_hash,
                attempt: 0,
                latency_ms: started.elapsed().as_secs_f64() * 1000.0,
                scope: cmd.scope.clone(),
                details: "cached=true".to_string(),
            });
            return Ok(existing.clone());
        }

        InsertAdapter::validate(db, &cmd.payload)?;
        let result = InsertAdapter::run(db, &cmd.payload);
        self.idempotency_store
            .insert(identity.clone(), result.clone());
        events.emit(CommandEvent {
            event_type: "command.success".to_string(),
            run_id: cmd.run_id.clone(),
            source: cmd.source.clone(),
            idempotency_key: cmd.idempotency_key.clone(),
            payload_hash,
            attempt: 1,
            latency_ms: started.elapsed().as_secs_f64() * 1000.0,
            scope: cmd.scope.clone(),
            details: format!("inserted={}", result.inserted),
        });
        Ok(result)
    }
}

fn build_demo_data(core: &mut WriteCore, db: &mut MiniPostgresLikeDb, events: &mut EventLog) {
    let mut rows = Vec::with_capacity(100_000);
    for i in 0..100_000 {
        let customer_id = if i % 2 == 0 {
            1
        } else if i % 2000 == 1 {
            4242
        } else {
            (i % 5000) as i32 + 2
        };
        rows.push(Row {
            order_id: i as i32 + 1,
            customer_id,
            amount: (i % 100) as i32 + 1,
            amount_with_tax: None,
        });
    }
    let cmd = InsertCommand {
        run_id: "run_orders_seed_001".to_string(),
        source: "demo".to_string(),
        scope: "workspace:default".to_string(),
        idempotency_key: "orders-seed-v1".to_string(),
        payload: InsertPayload {
            table: "orders".to_string(),
            rows,
        },
    };
    core.execute(db, events, &cmd).expect("seed insert should pass");
}

fn main() {
    println!("Mini PostgreSQL-like demo from B-tree theory (Rust/Cargo)\n");
    let mut db = MiniPostgresLikeDb::new(PlannerCosts::default());
    db.create_table("orders");

    let mut events = EventLog::default();
    let mut write_core = WriteCore::new();
    build_demo_data(&mut write_core, &mut db, &mut events);

    println!("1) Before creating index:");
    println!("{}", db.explain_analyze_eq("orders", "customer_id", 4242));

    db.create_index("orders", "customer_id", 64);
    println!("2) After creating B-tree index (selective predicate):");
    println!("{}", db.explain_analyze_eq("orders", "customer_id", 4242));

    println!("3) After creating B-tree index (non-selective predicate):");
    println!("{}", db.explain_analyze_eq("orders", "customer_id", 1));
    println!("Canonical events emitted: {}", events.events.len());
}
