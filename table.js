var filtersConfig = {
  // instruct TableFilter location to import ressources from
  base_path: 'https://arch4edu.github.io/tablefilter/',
  col_1: 'select',
  col_2: 'none',
  col_3: 'none',
  alternate_rows: true,
  rows_counter: true,
  btn_reset: true,
  loader: true,
  mark_active_columns: true,
  highlight_keywords: true,
  no_results_message: true,
  col_types: ['string', 'string', 'string', 'string', 'date'],
  extensions: [{ name: 'sort' }]
};

var tf = new TableFilter(document.querySelector('#content > table'), filtersConfig);
tf.init();
