use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};
use std::collections::HashMap;

use crate::common::{PlannerCosts, Row};
use crate::pg::MiniPostgresLikeDb;
use crate::product_journal::{
    append_tx_journal_op, create_tx_journal_file, load_recovery_journals,
    parse_snapshot_line, parse_wal_line, remove_tx_journal,
};

#[derive(Clone, Debug)]
pub enum WalOp {
    Insert(Row),
    Upsert(Row),
}

pub struct PersistentEngine {
    pub db: MiniPostgresLikeDb,
    table: String,
    root: PathBuf,
    data_version: u64,
    order_versions: HashMap<i32, u64>,
}

impl PersistentEngine {
    pub fn init(root: impl AsRef<Path>, table: &str) -> Result<Self, String> {
        let root = root.as_ref().to_path_buf();
        fs::create_dir_all(&root).map_err(|e| format!("create_dir_all failed: {e}"))?;

        let mut db = MiniPostgresLikeDb::new(PlannerCosts::default());
        db.create_table(table);

        let engine = Self {
            db,
            table: table.to_string(),
            root,
            data_version: 0,
            order_versions: HashMap::new(),
        };
        engine.ensure_files_exist()?;
        Ok(engine)
    }

    pub fn load_with_replay(root: impl AsRef<Path>, table: &str) -> Result<Self, String> {
        let mut engine = Self::init(root, table)?;
        engine.restore_snapshot()?;
        engine.replay_wal()?;
        Ok(engine)
    }

    pub fn insert(&mut self, row: Row) -> Result<(), String> {
        self.db.insert_row(&self.table, row.clone());
        self.bump_row_version(row.order_id);
        self.append_wal(&WalOp::Insert(row))
    }

    pub fn upsert_by_order_id(&mut self, row: Row) -> Result<(), String> {
        let mut replaced = false;
        if let Some(tbl) = self.db.tables.get_mut(&self.table) {
            for existing in &mut tbl.rows {
                if existing.order_id == row.order_id {
                    *existing = row.clone();
                    replaced = true;
                    break;
                }
            }
        }
        if !replaced {
            self.db.insert_row(&self.table, row.clone());
        }
        self.bump_row_version(row.order_id);
        self.rebuild_indexes_for_table();
        self.append_wal(&WalOp::Upsert(row))
    }

    pub fn create_customer_index(&mut self, order: usize) {
        self.db.create_index(&self.table, "customer_id", order);
    }

    pub fn explain_eq_customer(&self, customer_id: i32) -> String {
        self.db
            .explain_analyze_eq(&self.table, "customer_id", customer_id)
    }

    pub fn checkpoint(&self) -> Result<(), String> {
        let snapshot_path = self.snapshot_path();
        let mut file =
            File::create(snapshot_path).map_err(|e| format!("create snapshot failed: {e}"))?;

        if let Some(tbl) = self.db.tables.get(&self.table) {
            for row in &tbl.rows {
                let line = format!("{},{},{}\n", row.order_id, row.customer_id, row.amount);
                file.write_all(line.as_bytes())
                    .map_err(|e| format!("write snapshot failed: {e}"))?;
            }
        }

        File::create(self.wal_path()).map_err(|e| format!("truncate wal failed: {e}"))?;
        Ok(())
    }

    pub fn snapshot_rows(&self) -> Vec<Row> {
        self.db
            .tables
            .get(&self.table)
            .map(|t| t.rows.clone())
            .unwrap_or_default()
    }

    pub fn row_versions(&self) -> HashMap<i32, u64> {
        self.order_versions.clone()
    }

    fn ensure_files_exist(&self) -> Result<(), String> {
        fs::create_dir_all(self.tx_journal_dir_path())
            .map_err(|e| format!("create tx_journal dir failed: {e}"))?;
        if !self.snapshot_path().exists() {
            File::create(self.snapshot_path())
                .map_err(|e| format!("create snapshot file failed: {e}"))?;
        }
        if !self.wal_path().exists() {
            File::create(self.wal_path()).map_err(|e| format!("create wal file failed: {e}"))?;
        }
        Ok(())
    }

    fn restore_snapshot(&mut self) -> Result<(), String> {
        let file = File::open(self.snapshot_path())
            .map_err(|e| format!("open snapshot for restore failed: {e}"))?;
        let reader = BufReader::new(file);
        for line in reader.lines() {
            let line = line.map_err(|e| format!("read snapshot line failed: {e}"))?;
            if line.trim().is_empty() {
                continue;
            }
            if let Some(row) = parse_snapshot_line(&line)? {
                self.db.insert_row(&self.table, row);
                let last_order_id = self
                    .db
                    .tables
                    .get(&self.table)
                    .and_then(|t| t.rows.last())
                    .map(|r| r.order_id)
                    .unwrap_or_default();
                self.bump_row_version(last_order_id);
            }
        }
        Ok(())
    }

    fn replay_wal(&mut self) -> Result<(), String> {
        let file =
            File::open(self.wal_path()).map_err(|e| format!("open wal for replay failed: {e}"))?;
        let reader = BufReader::new(file);
        for line in reader.lines() {
            let line = line.map_err(|e| format!("read wal line failed: {e}"))?;
            if line.trim().is_empty() {
                continue;
            }
            let op = parse_wal_line(&line)?;
            match op {
                WalOp::Insert(row) => {
                    self.db.insert_row(&self.table, row.clone());
                    self.bump_row_version(row.order_id);
                }
                WalOp::Upsert(row) => {
                    let mut replaced = false;
                    if let Some(tbl) = self.db.tables.get_mut(&self.table) {
                        for existing in &mut tbl.rows {
                            if existing.order_id == row.order_id {
                                *existing = row.clone();
                                replaced = true;
                                break;
                            }
                        }
                    }
                    if !replaced {
                        self.db.insert_row(&self.table, row.clone());
                    }
                    self.bump_row_version(row.order_id);
                }
            }
        }
        self.rebuild_indexes_for_table();
        Ok(())
    }

    fn append_wal(&self, op: &WalOp) -> Result<(), String> {
        let mut file = OpenOptions::new()
            .append(true)
            .create(true)
            .open(self.wal_path())
            .map_err(|e| format!("open wal append failed: {e}"))?;

        let line = match op {
            WalOp::Insert(row) => format!("I,{},{},{}\n", row.order_id, row.customer_id, row.amount),
            WalOp::Upsert(row) => format!("U,{},{},{}\n", row.order_id, row.customer_id, row.amount),
        };
        file.write_all(line.as_bytes())
            .map_err(|e| format!("write wal failed: {e}"))
    }

    fn rebuild_indexes_for_table(&mut self) {
        if self
            .db
            .indexes
            .contains_key(&format!("{}.customer_id", self.table))
        {
            self.db.create_index(&self.table, "customer_id", 64);
        }
    }

    fn snapshot_path(&self) -> PathBuf {
        self.root.join("snapshot.csv")
    }

    fn wal_path(&self) -> PathBuf {
        self.root.join("wal.log")
    }

    fn tx_journal_dir_path(&self) -> PathBuf {
        self.root.join("tx_journal")
    }

    fn root_path(&self) -> PathBuf {
        self.root.clone()
    }

    fn bump_row_version(&mut self, order_id: i32) {
        self.data_version += 1;
        self.order_versions.insert(order_id, self.data_version);
    }
}

#[derive(Clone)]
pub struct ConcurrentEngine {
    inner: Arc<RwLock<PersistentEngine>>,
    tx_state: Arc<RwLock<TxState>>,
    journal_dir: PathBuf,
}

impl ConcurrentEngine {
    pub fn new(engine: PersistentEngine) -> Self {
        let journal_dir = engine.root_path().join("tx_journal");
        let recovery = load_recovery_journals(&journal_dir).unwrap_or_default();
        let max_recovery_id = recovery.keys().copied().max().unwrap_or(0);
        Self {
            inner: Arc::new(RwLock::new(engine)),
            tx_state: Arc::new(RwLock::new(TxState {
                next_tx_id: max_recovery_id,
                active: HashMap::new(),
                write_lock_owner: None,
                recovery,
            })),
            journal_dir,
        }
    }

    pub fn read_explain(&self, customer_id: i32) -> Result<String, String> {
        let guard = self
            .inner
            .read()
            .map_err(|_| "rwlock poisoned on read".to_string())?;
        Ok(guard.explain_eq_customer(customer_id))
    }

    pub fn write_insert(&self, row: Row) -> Result<(), String> {
        let mut guard = self
            .inner
            .write()
            .map_err(|_| "rwlock poisoned on write".to_string())?;
        guard.insert(row)
    }

    pub fn write_upsert(&self, row: Row) -> Result<(), String> {
        let mut guard = self
            .inner
            .write()
            .map_err(|_| "rwlock poisoned on write".to_string())?;
        guard.upsert_by_order_id(row)
    }

    pub fn begin(&self) -> Result<u64, String> {
        let (snapshot_rows, observed_versions) = {
            let engine = self
                .inner
                .read()
                .map_err(|_| "rwlock poisoned on read".to_string())?;
            (engine.snapshot_rows(), engine.row_versions())
        };
        let mut tx = self
            .tx_state
            .write()
            .map_err(|_| "rwlock poisoned on tx write".to_string())?;
        tx.next_tx_id += 1;
        let tx_id = tx.next_tx_id;
        tx.active.insert(
            tx_id,
            TxContext {
                snapshot_rows,
                observed_versions,
                staged_ops: Vec::new(),
                has_write_lock: false,
            },
        );
        create_tx_journal_file(&self.journal_dir, tx_id)?;
        Ok(tx_id)
    }

    pub fn tx_insert(&self, tx_id: u64, row: Row) -> Result<(), String> {
        let mut tx = self
            .tx_state
            .write()
            .map_err(|_| "rwlock poisoned on tx write".to_string())?;
        acquire_write_lock(&mut tx, tx_id)?;
        let ctx = tx
            .active
            .get_mut(&tx_id)
            .ok_or_else(|| "transaction not found".to_string())?;
        let op = TxStagedOp {
            op: WalOp::Insert(row),
            observed_version: None,
        };
        append_tx_journal_op(&self.journal_dir, tx_id, &op)?;
        ctx.staged_ops.push(op);
        ctx.has_write_lock = true;
        Ok(())
    }

    pub fn tx_upsert(&self, tx_id: u64, row: Row) -> Result<(), String> {
        let mut tx = self
            .tx_state
            .write()
            .map_err(|_| "rwlock poisoned on tx write".to_string())?;
        acquire_write_lock(&mut tx, tx_id)?;
        let ctx = tx
            .active
            .get_mut(&tx_id)
            .ok_or_else(|| "transaction not found".to_string())?;
        let observed = ctx.observed_versions.get(&row.order_id).copied().unwrap_or(0);
        let op = TxStagedOp {
            op: WalOp::Upsert(row),
            observed_version: Some(observed),
        };
        append_tx_journal_op(&self.journal_dir, tx_id, &op)?;
        ctx.staged_ops.push(op);
        ctx.has_write_lock = true;
        Ok(())
    }

    pub fn tx_read_snapshot_explain(&self, tx_id: u64, customer_id: i32) -> Result<String, String> {
        let tx = self
            .tx_state
            .read()
            .map_err(|_| "rwlock poisoned on tx read".to_string())?;
        let ctx = tx
            .active
            .get(&tx_id)
            .ok_or_else(|| "transaction not found".to_string())?;
        let mut hits = 0usize;
        let mut removed = 0usize;
        for row in &ctx.snapshot_rows {
            if row.customer_id == customer_id {
                hits += 1;
            } else {
                removed += 1;
            }
        }
        Ok(format!(
            "TX SNAPSHOT EXPLAIN\n\
             Seq Scan (snapshot)\n\
               Filter: (customer_id = {customer_id})\n\
               Rows Removed by Filter: {removed}\n\
               Actual Rows: {hits}\n"
        ))
    }

    pub fn commit(&self, tx_id: u64) -> Result<(), String> {
        let ctx_opt = {
            let mut tx = self
                .tx_state
                .write()
                .map_err(|_| "rwlock poisoned on tx write".to_string())?;
            if tx.write_lock_owner.is_some() && tx.write_lock_owner != Some(tx_id) {
                return Err("transaction does not own write lock".to_string());
            }
            tx.write_lock_owner = None;
            tx.active.remove(&tx_id)
        };

        let staged_ops = if let Some(ctx) = ctx_opt {
            ctx.staged_ops
        } else {
            let mut tx = self
                .tx_state
                .write()
                .map_err(|_| "rwlock poisoned on tx write".to_string())?;
            tx.recovery
                .remove(&tx_id)
                .ok_or_else(|| "transaction not found".to_string())?
        };

        let mut engine = self
            .inner
            .write()
            .map_err(|_| "rwlock poisoned on engine write".to_string())?;

        for staged in &staged_ops {
            if let WalOp::Upsert(row) = &staged.op {
                let observed = staged.observed_version.unwrap_or(0);
                let current = engine.row_versions().get(&row.order_id).copied().unwrap_or(0);
                if current != observed {
                    return Err(format!(
                        "write-write conflict for order_id={} (observed {}, current {})",
                        row.order_id, observed, current
                    ));
                }
            }
        }

        for staged in staged_ops {
            match staged.op {
                WalOp::Insert(row) => engine.insert(row)?,
                WalOp::Upsert(row) => engine.upsert_by_order_id(row)?,
            }
        }
        remove_tx_journal(&self.journal_dir, tx_id)?;
        Ok(())
    }

    pub fn rollback(&self, tx_id: u64) -> Result<(), String> {
        let mut tx = self
            .tx_state
            .write()
            .map_err(|_| "rwlock poisoned on tx write".to_string())?;
        tx.active
            .remove(&tx_id);
        tx.recovery.remove(&tx_id);
        if tx.write_lock_owner == Some(tx_id) {
            tx.write_lock_owner = None;
        }
        remove_tx_journal(&self.journal_dir, tx_id)?;
        Ok(())
    }

    pub fn list_recovery_transactions(&self) -> Result<Vec<u64>, String> {
        let tx = self
            .tx_state
            .read()
            .map_err(|_| "rwlock poisoned on tx read".to_string())?;
        let mut ids: Vec<u64> = tx.recovery.keys().copied().collect();
        ids.sort_unstable();
        Ok(ids)
    }
}

#[derive(Default)]
struct TxState {
    next_tx_id: u64,
    active: HashMap<u64, TxContext>,
    write_lock_owner: Option<u64>,
    recovery: HashMap<u64, Vec<TxStagedOp>>,
}

struct TxContext {
    snapshot_rows: Vec<Row>,
    observed_versions: HashMap<i32, u64>,
    staged_ops: Vec<TxStagedOp>,
    has_write_lock: bool,
}

#[derive(Clone)]
pub(crate) struct TxStagedOp {
    pub(crate) op: WalOp,
    pub(crate) observed_version: Option<u64>,
}

fn acquire_write_lock(tx: &mut TxState, tx_id: u64) -> Result<(), String> {
    match tx.write_lock_owner {
        Some(owner) if owner != tx_id => Err("table write lock is held by another transaction".to_string()),
        _ => {
            tx.write_lock_owner = Some(tx_id);
            Ok(())
        }
    }
}

