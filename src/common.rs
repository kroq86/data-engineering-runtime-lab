use std::collections::{BTreeMap, hash_map::DefaultHasher};
use std::hash::{Hash, Hasher};

#[derive(Clone, Debug)]
pub struct Row {
    pub order_id: i32,
    pub customer_id: i32,
    pub amount: i32,
    pub amount_with_tax: Option<f64>,
}

#[derive(Clone, Debug)]
pub struct PlannerCosts {
    pub seq_page_cost: f64,
    pub random_page_cost: f64,
    pub cpu_tuple_cost: f64,
    pub tuples_per_page: usize,
    pub index_entries_per_page: usize,
}

impl Default for PlannerCosts {
    fn default() -> Self {
        Self {
            seq_page_cost: 1.0,
            random_page_cost: 4.0,
            cpu_tuple_cost: 0.01,
            tuples_per_page: 128,
            index_entries_per_page: 256,
        }
    }
}

#[derive(Clone, Debug)]
pub struct BTreeIndex {
    pub order: usize,
    pub height: usize,
    pub values: BTreeMap<i32, Vec<usize>>,
}

impl BTreeIndex {
    pub fn new(order: usize) -> Self {
        let fixed_order = if order < 3 { 3 } else { order };
        Self {
            order: fixed_order,
            height: 1,
            values: BTreeMap::new(),
        }
    }

    pub fn insert(&mut self, key: i32, row_id: usize) {
        self.values.entry(key).or_default().push(row_id);
        self.height = approx_btree_height(self.values.len(), self.order);
    }

    pub fn search(&self, key: i32) -> Vec<usize> {
        self.values.get(&key).cloned().unwrap_or_default()
    }
}

pub fn approx_btree_height(unique_keys: usize, order: usize) -> usize {
    if unique_keys <= 1 {
        return 1;
    }
    let fanout = order.max(3);
    let mut nodes = unique_keys;
    let mut h = 1;
    while nodes > 1 {
        nodes = nodes.div_ceil(fanout);
        h += 1;
    }
    h
}

#[allow(dead_code)]
#[derive(Clone, Debug)]
pub struct CommandEvent {
    pub event_type: String,
    pub run_id: String,
    pub source: String,
    pub idempotency_key: String,
    pub payload_hash: u64,
    pub attempt: usize,
    pub latency_ms: f64,
    pub scope: String,
    pub details: String,
}

#[derive(Default)]
pub struct EventLog {
    pub events: Vec<CommandEvent>,
}

impl EventLog {
    pub fn emit(&mut self, event: CommandEvent) {
        self.events.push(event);
    }
}

pub fn stable_hash(s: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    s.hash(&mut hasher);
    hasher.finish()
}
