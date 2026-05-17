// plotly.js-basic-dist-min ships JS only; reuse the upstream plotly.js types.
declare module "plotly.js-basic-dist-min" {
  import type * as Plotly from "plotly.js";
  const value: typeof Plotly;
  export default value;
}
