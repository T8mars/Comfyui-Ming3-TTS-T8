import { app } from "../../../scripts/app.js";

const fields = {
  seed: ["language"], multilingual: ["language"], paralinguistic: ["language"],
  podcast: [], basic: ["speed", "pitch", "volume"], emotion: ["emotion"],
  dialect: ["dialect"], freeform: ["instruction"], voice_design: ["style"], ip: ["ip"],
};

app.registerExtension({
  name: "T8.Ming.Native",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!nodeData.name.startsWith("MingT8")) return;
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      original?.apply(this, arguments);
      this.boxcolor = "#fb7299";
      if (!["MingT8Task", "MingT8OneClick"].includes(nodeData.name)) return;
      const task = this.widgets?.find(w => w.name === "task");
      if (!task) return;
      const update = () => {
        const language = this.widgets?.find(w => w.name === "language");
        if (language && ["seed", "multilingual", "paralinguistic"].includes(task.value)) {
          const values = task.value === "multilingual" ? ["German", "Spanish", "French", "Korean", "Japanese"] : ["Chinese", "English"];
          language.options.values = values;
          if (!values.includes(language.value)) language.value = values[0];
        }
        const visible = new Set(["task", "text", ...(fields[task.value] || [])]);
        const referenceControls=nodeData.name==="MingT8OneClick"?["auto_transcribe","reference_text","reference_start","reference_end"]:[];
        if(["seed","multilingual","paralinguistic"].includes(task.value))referenceControls.forEach(name=>visible.add(name));
        else if(["basic","emotion","dialect","freeform"].includes(task.value)){visible.add("reference_start");visible.add("reference_end");}
        for (const widget of this.widgets || []) {
          if (![...Object.values(fields).flat(),...referenceControls].includes(widget.name)) continue;
          widget._mingType ??= widget.type;
          widget._mingSize ??= widget.computeSize;
          widget.type = visible.has(widget.name) ? widget._mingType : "converted-widget";
          widget.computeSize = visible.has(widget.name) ? widget._mingSize : () => [0, -4];
        }
        this.setSize(this.computeSize());
        this.setDirtyCanvas(true, true);
      };
      const callback = task.callback;
      task.callback = function () { callback?.apply(this, arguments); update(); };
      setTimeout(update, 0);
    };
  },
});
