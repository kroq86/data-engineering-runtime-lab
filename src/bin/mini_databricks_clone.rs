use mini_data_systems::common::{CommandEvent, EventLog, PlannerCosts, Row, stable_hash};
use mini_data_systems::pg::MiniPostgresLikeDb;
use std::collections::{HashMap, HashSet, VecDeque};
use std::time::Instant;

#[derive(Clone, Debug)]
struct DeltaCommit {
    version: usize,
    operation: String,
    row_count: usize,
}

#[derive(Clone, Debug)]
struct MiniDeltaTable {
    versions: Vec<Vec<Row>>,
    log: Vec<DeltaCommit>,
}

impl MiniDeltaTable {
    fn new() -> Self {
        Self {
            versions: vec![Vec::new()],
            log: Vec::new(),
        }
    }

    fn current_version(&self) -> usize {
        self.versions.len() - 1
    }

    fn snapshot(&self, version: Option<usize>) -> Vec<Row> {
        self.versions[version.unwrap_or_else(|| self.current_version())].clone()
    }

    fn append(&mut self, rows: &[Row]) {
        let mut next = self.snapshot(None);
        next.extend_from_slice(rows);
        self.versions.push(next);
        self.log.push(DeltaCommit {
            version: self.current_version(),
            operation: "append".to_string(),
            row_count: rows.len(),
        });
    }

    fn merge_upsert(&mut self, rows: &[Row]) {
        let mut by_id: HashMap<i32, Row> = HashMap::new();
        for row in self.snapshot(None) {
            by_id.insert(row.order_id, row);
        }
        for row in rows {
            by_id.insert(row.order_id, row.clone());
        }
        self.versions.push(by_id.into_values().collect());
        self.log.push(DeltaCommit {
            version: self.current_version(),
            operation: "merge_upsert".to_string(),
            row_count: rows.len(),
        });
    }
}

#[derive(Clone, Debug)]
enum Operation {
    Append,
    MergeUpsert,
}

#[derive(Clone, Debug)]
struct WritePayload {
    operation: Operation,
    rows: Vec<Row>,
}

#[derive(Clone, Debug)]
struct WriteCommand {
    run_id: String,
    source: String,
    scope: String,
    idempotency_key: String,
    payload: WritePayload,
}

#[derive(Clone, Debug)]
struct WriteResult {
    version: usize,
}

struct WriteCore {
    idem: HashMap<String, WriteResult>,
}

impl WriteCore {
    fn new() -> Self {
        Self {
            idem: HashMap::new(),
        }
    }

    fn execute(
        &mut self,
        table: &mut MiniDeltaTable,
        events: &mut EventLog,
        cmd: &WriteCommand,
    ) -> Result<WriteResult, String> {
        if cmd.payload.rows.is_empty() {
            return Err("rows must be non-empty".to_string());
        }
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
            details: "start".to_string(),
        });

        if let Some(existing) = self.idem.get(&identity) {
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

        match cmd.payload.operation {
            Operation::Append => table.append(&cmd.payload.rows),
            Operation::MergeUpsert => table.merge_upsert(&cmd.payload.rows),
        }
        let res = WriteResult {
            version: table.current_version(),
        };
        self.idem.insert(identity, res.clone());
        events.emit(CommandEvent {
            event_type: "command.success".to_string(),
            run_id: cmd.run_id.clone(),
            source: cmd.source.clone(),
            idempotency_key: cmd.idempotency_key.clone(),
            payload_hash,
            attempt: 1,
            latency_ms: started.elapsed().as_secs_f64() * 1000.0,
            scope: cmd.scope.clone(),
            details: format!("version={}", res.version),
        });
        Ok(res)
    }
}

struct MiniSparkEngine;

impl MiniSparkEngine {
    fn partition(rows: &[Row], n_parts: usize) -> Vec<Vec<Row>> {
        let size = n_parts.max(1);
        let mut parts = vec![Vec::<Row>::new(); size];
        for (i, row) in rows.iter().enumerate() {
            parts[i % size].push(row.clone());
        }
        parts
    }

    fn map_with_tax(parts: Vec<Vec<Row>>) -> Vec<Vec<Row>> {
        parts
            .into_iter()
            .map(|p| {
                p.into_iter()
                    .map(|mut r| {
                        r.amount_with_tax = Some((r.amount as f64) * 1.2);
                        r
                    })
                    .collect::<Vec<Row>>()
            })
            .collect()
    }

    fn collect(parts: Vec<Vec<Row>>) -> Vec<Row> {
        parts.into_iter().flatten().collect()
    }
}

#[derive(Default)]
struct MiniWorkflow {
    deps: HashMap<String, HashSet<String>>,
}

impl MiniWorkflow {
    fn add_task(&mut self, task: &str, depends_on: &[&str]) {
        let dep_keys: Vec<String> = depends_on.iter().map(|d| (*d).to_string()).collect();
        let entry = self.deps.entry(task.to_string()).or_default();
        for dep in depends_on {
            entry.insert((*dep).to_string());
        }
        for dep_key in dep_keys {
            self.deps.entry(dep_key).or_default();
        }
    }

    fn run(&self) -> Result<Vec<String>, String> {
        let mut indeg: HashMap<String, usize> = HashMap::new();
        let mut children: HashMap<String, Vec<String>> = HashMap::new();
        for (task, dset) in &self.deps {
            indeg.insert(task.clone(), dset.len());
            for d in dset {
                children.entry(d.clone()).or_default().push(task.clone());
            }
        }
        let mut q: VecDeque<String> = indeg
            .iter()
            .filter_map(|(k, v)| if *v == 0 { Some(k.clone()) } else { None })
            .collect();
        let mut order = Vec::<String>::new();
        while let Some(task) = q.pop_front() {
            order.push(task.clone());
            if let Some(ch) = children.get(&task) {
                for c in ch {
                    if let Some(v) = indeg.get_mut(c) {
                        *v -= 1;
                        if *v == 0 {
                            q.push_back(c.clone());
                        }
                    }
                }
            }
        }
        if order.len() != indeg.len() {
            return Err("cycle detected".to_string());
        }
        Ok(order)
    }
}

#[derive(Default)]
struct MiniMlflow {
    runs: Vec<String>,
    models: HashMap<String, String>,
}

#[derive(Default)]
struct MiniCatalog {
    acl: HashMap<String, HashMap<String, HashSet<String>>>,
}

fn main() {
    println!("Minimal Databricks-like clone demo (Rust/Cargo)\n");

    let mut bronze = MiniDeltaTable::new();
    let mut log = EventLog::default();
    let mut core = WriteCore::new();

    let mut seed = Vec::<Row>::new();
    for i in 1..=5000 {
        seed.push(Row {
            order_id: i,
            customer_id: if i % 1000 == 0 { 4242 } else { 1 },
            amount: i % 100,
            amount_with_tax: None,
        });
    }
    let cmd1 = WriteCommand {
        run_id: "run_ingest_001".to_string(),
        source: "demo".to_string(),
        scope: "workspace:default".to_string(),
        idempotency_key: "orders-bronze-append-v1".to_string(),
        payload: WritePayload {
            operation: Operation::Append,
            rows: seed,
        },
    };
    core.execute(&mut bronze, &mut log, &cmd1)
        .expect("append must pass");

    let cmd2 = WriteCommand {
        run_id: "run_ingest_002".to_string(),
        source: "demo".to_string(),
        scope: "workspace:default".to_string(),
        idempotency_key: "orders-bronze-upsert-v1".to_string(),
        payload: WritePayload {
            operation: Operation::MergeUpsert,
            rows: vec![Row {
                order_id: 5000,
                customer_id: 4242,
                amount: 35,
                amount_with_tax: None,
            }],
        },
    };
    core.execute(&mut bronze, &mut log, &cmd2)
        .expect("upsert must pass");

    println!("Delta current version: {}", bronze.current_version());
    println!("Version 1 snapshot rows: {}", bronze.snapshot(Some(1)).len());
    println!("Version 2 snapshot rows: {}", bronze.snapshot(Some(2)).len());
    if let Some(last) = bronze.log.last() {
        println!(
            "Last delta commit: version={}, op={}, rows={}",
            last.version, last.operation, last.row_count
        );
    }

    let parts = MiniSparkEngine::partition(&bronze.snapshot(None), 2);
    let transformed = MiniSparkEngine::map_with_tax(parts);
    let silver_rows = MiniSparkEngine::collect(transformed);
    println!("Spark partitions: 2, transformed rows: {}", silver_rows.len());

    let mut warehouse = MiniPostgresLikeDb::new(PlannerCosts::default());
    warehouse.create_table("orders_silver");
    for row in silver_rows {
        warehouse.insert_row("orders_silver", row);
    }
    println!("\nSQL Warehouse (before index):");
    println!(
        "{}",
        warehouse.explain_analyze_eq("orders_silver", "customer_id", 4242)
    );
    warehouse.create_index("orders_silver", "customer_id", 64);
    println!("SQL Warehouse (after index):");
    println!(
        "{}",
        warehouse.explain_analyze_eq("orders_silver", "customer_id", 4242)
    );

    let mut wf = MiniWorkflow::default();
    wf.add_task("extract", &[]);
    wf.add_task("transform", &["extract"]);
    wf.add_task("serve_sql", &["transform"]);
    let order = wf.run().expect("DAG must be acyclic");
    println!("Workflow execution order: {:?}", order);

    let mut ml = MiniMlflow::default();
    ml.runs.push("run_001".to_string());
    ml.models
        .insert("churn_model".to_string(), "run_001".to_string());
    println!(
        "Registered model churn_model -> {}",
        ml.models.get("churn_model").unwrap_or(&"none".to_string())
    );

    let mut catalog = MiniCatalog::default();
    catalog
        .acl
        .entry("orders_silver".to_string())
        .or_default()
        .entry("analyst_team".to_string())
        .or_default()
        .insert("SELECT".to_string());
    let can_select = catalog
        .acl
        .get("orders_silver")
        .and_then(|x| x.get("analyst_team"))
        .is_some_and(|p| p.contains("SELECT"));
    println!(
        "Catalog access analyst_team SELECT orders_silver: {}",
        can_select
    );
    println!("Canonical events emitted: {}", log.events.len());
}
