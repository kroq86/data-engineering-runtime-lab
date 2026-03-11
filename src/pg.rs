use std::collections::HashMap;
use std::time::Instant;

use crate::common::{BTreeIndex, PlannerCosts, Row};

#[derive(Clone, Debug, Default)]
pub struct HeapTable {
    pub rows: Vec<Row>,
}

pub struct MiniPostgresLikeDb {
    pub tables: HashMap<String, HeapTable>,
    pub indexes: HashMap<String, BTreeIndex>,
    pub distinct_stats: HashMap<String, HashMap<i32, usize>>,
    pub costs: PlannerCosts,
}

impl MiniPostgresLikeDb {
    pub fn new(costs: PlannerCosts) -> Self {
        Self {
            tables: HashMap::new(),
            indexes: HashMap::new(),
            distinct_stats: HashMap::new(),
            costs,
        }
    }

    pub fn create_table(&mut self, name: &str) {
        self.tables.insert(name.to_string(), HeapTable::default());
    }

    pub fn insert_row(&mut self, table: &str, row: Row) {
        if let Some(tbl) = self.tables.get_mut(table) {
            let row_id = tbl.rows.len();
            tbl.rows.push(row.clone());
            let idx_key = format!("{table}.customer_id");
            if let Some(idx) = self.indexes.get_mut(&idx_key) {
                idx.insert(row.customer_id, row_id);
            }
        }
    }

    pub fn create_index(&mut self, table: &str, column: &str, order: usize) {
        let tbl = match self.tables.get(table) {
            Some(t) => t,
            None => return,
        };
        let mut idx = BTreeIndex::new(order);
        let mut stats: HashMap<i32, usize> = HashMap::new();
        for (row_id, row) in tbl.rows.iter().enumerate() {
            let value = match column {
                "customer_id" => row.customer_id,
                "order_id" => row.order_id,
                "amount" => row.amount,
                _ => 0,
            };
            idx.insert(value, row_id);
            *stats.entry(value).or_insert(0) += 1;
        }
        self.indexes.insert(format!("{table}.{column}"), idx);
        self.distinct_stats.insert(format!("{table}.{column}"), stats);
    }

    pub fn explain_analyze_eq(&self, table: &str, column: &str, value: i32) -> String {
        let Some(tbl) = self.tables.get(table) else {
            return "table not found".to_string();
        };
        let has_index = self.indexes.contains_key(&format!("{table}.{column}"));
        let (total_rows, est_rows) = self.estimate_rows(table, column, value);
        let seq_cost = self.seq_scan_cost(total_rows);
        let idx_cost = if has_index {
            self.index_scan_cost(table, column, est_rows)
        } else {
            f64::INFINITY
        };
        let plan = if has_index && idx_cost < seq_cost {
            "Index Scan"
        } else {
            "Seq Scan"
        };

        let started = Instant::now();
        if plan == "Seq Scan" {
            let mut hits = 0usize;
            let mut removed = 0usize;
            for row in &tbl.rows {
                let v = match column {
                    "customer_id" => row.customer_id,
                    "order_id" => row.order_id,
                    "amount" => row.amount,
                    _ => i32::MIN,
                };
                if v == value {
                    hits += 1;
                } else {
                    removed += 1;
                }
            }
            let elapsed = started.elapsed().as_secs_f64() * 1000.0;
            return format!(
                "EXPLAIN ANALYZE\n\
                 Seq Scan on {table}\n\
                   Filter: ({column} = {value})\n\
                   Estimated Cost: {seq_cost:.2}\n\
                   Estimated Rows: {est_rows}\n\
                   Rows Removed by Filter: {removed}\n\
                   Actual Rows: {hits}\n\
                   Execution Time: {elapsed:.3} ms\n"
            );
        }

        let idx = self
            .indexes
            .get(&format!("{table}.{column}"))
            .expect("index exists when plan is index scan");
        let hits = idx.search(value).len();
        let elapsed = started.elapsed().as_secs_f64() * 1000.0;
        format!(
            "EXPLAIN ANALYZE\n\
             Index Scan using {table}_{column}_idx on {table}\n\
               Index Cond: ({column} = {value})\n\
               Estimated Cost: {idx_cost:.2}\n\
               Estimated Rows: {est_rows}\n\
               B-Tree Height: {}\n\
               Heap Fetches: {hits}\n\
               Actual Rows: {hits}\n\
               Execution Time: {elapsed:.3} ms\n",
            idx.height
        )
    }

    fn estimate_rows(&self, table: &str, column: &str, value: i32) -> (usize, usize) {
        let total_rows = self.tables.get(table).map_or(0, |t| t.rows.len());
        let selectivity = self.estimate_selectivity(table, column, value);
        let est_rows = ((total_rows as f64) * selectivity).round().max(1.0) as usize;
        (total_rows, est_rows)
    }

    fn estimate_selectivity(&self, table: &str, column: &str, value: i32) -> f64 {
        let total = self.tables.get(table).map_or(1, |t| t.rows.len().max(1)) as f64;
        if let Some(stats) = self.distinct_stats.get(&format!("{table}.{column}")) {
            let freq = *stats.get(&value).unwrap_or(&0) as f64;
            return freq / total;
        }
        0.20
    }

    fn seq_scan_cost(&self, total_rows: usize) -> f64 {
        let pages = total_rows.div_ceil(self.costs.tuples_per_page).max(1) as f64;
        let io = pages * self.costs.seq_page_cost;
        let cpu = (total_rows as f64) * self.costs.cpu_tuple_cost;
        io + cpu
    }

    fn index_scan_cost(&self, table: &str, column: &str, est_rows: usize) -> f64 {
        let Some(idx) = self.indexes.get(&format!("{table}.{column}")) else {
            return f64::INFINITY;
        };
        let descent = (idx.height as f64) * self.costs.random_page_cost;
        let leaf_pages = est_rows.div_ceil(self.costs.index_entries_per_page).max(1) as f64;
        let index_leaf = leaf_pages * self.costs.random_page_cost;
        let heap_pages = est_rows.div_ceil(self.costs.tuples_per_page).max(1) as f64;
        let heap_fetch = heap_pages * self.costs.random_page_cost;
        let cpu = (est_rows as f64) * (self.costs.cpu_tuple_cost * 2.0);
        descent + index_leaf + heap_fetch + cpu
    }
}
