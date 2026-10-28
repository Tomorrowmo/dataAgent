window.__ModuleLoader__.load({
	id: "@rlab/dsh-client-ui-dataagent",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react = require("react");
		//#region lib/types/client/shared.js
		/**
		* Shared helpers for the keyed tool views.
		*
		* Everything here derives from the durable call/result slice only — no live
		* service reads, no clock, no randomness — so a view replays identically from
		* the session log.
		*
		* @module
		*/
		/** Classify a call without consulting anything outside its own slice. */
		function callState(block) {
			if (!("kind" in block)) return "running";
			if (block.error?.code === "interrupted") return "stopped";
			return block.isError ? "error" : "ok";
		}
		/**
		* Read the card data a tool projected through `output.presentationMeta`.
		*
		* This is the only structured payload a view may rely on. The canonical return
		* value is not persisted, and the content blocks carry prose written for the
		* model — parsing that prose back into fields would break the moment the
		* wording changed. `presentationMeta` exists precisely so the card has its own
		* replayable contract.
		*
		* Returns `null` while the call is still running, when the producing tool
		* projected nothing, or when an older log predates the projection — every one
		* of which is a normal state the caller handles by falling back to text.
		*/
		function cardMeta(block) {
			if (!("kind" in block)) return null;
			const meta = block.meta;
			return meta === void 0 || meta === null ? null : meta;
		}
		/** Flatten the durable result blocks to text, matching ui-tool's generic row. */
		function resultText(block) {
			if (!("kind" in block)) return null;
			const parts = [];
			for (const item of block.content) parts.push(item.type === "text" ? item.text : JSON.stringify(item, null, 2));
			if (parts.length === 0 && block.error !== void 0) parts.push(`${block.error.name}: ${block.error.code}`);
			return parts.join("\n") || null;
		}
		/** Read the call arguments, tolerating the truncated JSON prefix a stream can expose. */
		function callArgs(block) {
			const raw = ("kind" in block ? block.call?.argsRaw : block.argsRaw) ?? "";
			if (raw === "") return {};
			try {
				const parsed = JSON.parse(raw);
				return typeof parsed === "object" && parsed !== null ? parsed : {};
			} catch {
				return {};
			}
		}
		//#endregion
		//#region lib/types/client/AlgoRunRow.js
		/**
		* Keyed tool view for `algo_run`.
		*
		* Shows the lineage edge the run created — parent dataset, operation, result —
		* because that edge is the product's claim to traceability. A line of prose
		* saying "saved as #263" makes the reader reconstruct the graph in their head;
		* the arrow shows it.
		*
		* Pure function of the durable slice, so it replays identically from the log.
		*/
		function node(label, sub) {
			return (0, react.createElement)("div", { style: {
				border: "1px solid currentColor",
				padding: "0.4em 0.7em",
				display: "flex",
				flexDirection: "column",
				gap: "0.1em",
				minWidth: 0
			} }, (0, react.createElement)("strong", { style: { whiteSpace: "nowrap" } }, label), (0, react.createElement)("span", { style: {
				fontSize: "0.85em",
				opacity: .7
			} }, sub));
		}
		function AlgoRunRow({ block }) {
			const state = callState(block);
			const args = callArgs(block);
			const meta = cardMeta(block);
			if (state === "running") return (0, react.createElement)("div", { style: { opacity: .7 } }, `正在用 ${args.slug ?? "算法"} 处理数据集 #${args.dataset_id ?? "?"}…`);
			if (meta === null) return (0, react.createElement)("pre", { style: {
				whiteSpace: "pre-wrap",
				margin: 0,
				fontFamily: "inherit"
			} }, resultText(block) ?? "（无结果）");
			return (0, react.createElement)("div", { style: {
				display: "flex",
				alignItems: "center",
				gap: "0.6em",
				flexWrap: "wrap",
				lineHeight: 1.5
			} }, node(`#${meta.derivedFrom}`, "源数据"), (0, react.createElement)("span", { style: {
				opacity: .6,
				whiteSpace: "nowrap"
			} }, `── ${meta.algorithm} →`), node(`#${meta.datasetId}`, `${meta.rows} 行 × ${meta.columns} 列`), (0, react.createElement)("span", { style: {
				opacity: .7,
				minWidth: 0,
				wordBreak: "break-word"
			} }, meta.name));
		}
		//#endregion
		//#region lib/types/client/WtFindingsRow.js
		/**
		* Keyed tool view for `wt_findings`.
		*
		* The point of this view is one distinction: an item that was **assessed and
		* failed** is not the same as an item that could **not be assessed**. In a flat
		* text dump those read alike, and a 未评定 item mistaken for a pass is the exact
		* failure this module exists to prevent. So the two live in separate blocks
		* with different labels, and the unassessed block states what is missing.
		*
		* Pure function of the durable slice — no service reads, no clock — so it
		* replays identically from the session log.
		*/
		/** Severity ordering used only for the accent colour; the label itself comes from the host. */
		const LEVEL_TONE = {
			critical: "#9E3A38",
			严重: "#9E3A38",
			warning: "#8F6318",
			警告: "#8F6318",
			notice: "#4A6572",
			提示: "#4A6572"
		};
		function tone(level) {
			return LEVEL_TONE[level] ?? "#4A6572";
		}
		function field(label, value) {
			if (!value) return null;
			return (0, react.createElement)("div", { style: {
				display: "flex",
				gap: "0.5em",
				lineHeight: 1.7
			} }, (0, react.createElement)("span", { style: {
				opacity: .6,
				flex: "none",
				minWidth: "5em"
			} }, label), (0, react.createElement)("span", null, value));
		}
		function WtFindingsRow({ block }) {
			const state = callState(block);
			const args = callArgs(block);
			const meta = cardMeta(block);
			if (state === "running") return (0, react.createElement)("div", { style: { opacity: .7 } }, `正在读取车次 ${args.run_no ?? ""} 的判定…`);
			if (meta === null) return (0, react.createElement)("pre", { style: {
				whiteSpace: "pre-wrap",
				margin: 0,
				fontFamily: "inherit"
			} }, resultText(block) ?? "（无结果）");
			const problems = meta.problems ?? [];
			const unavailable = meta.unavailable ?? [];
			return (0, react.createElement)("div", { style: {
				display: "flex",
				flexDirection: "column",
				gap: "0.9em"
			} }, (0, react.createElement)("div", { style: {
				display: "flex",
				alignItems: "baseline",
				gap: "0.75em"
			} }, (0, react.createElement)("strong", null, `车次 ${meta.runNo}`), (0, react.createElement)("span", { style: {
				border: "1px solid currentColor",
				padding: "0.05em 0.5em",
				fontSize: "0.85em",
				color: meta.grade.startsWith("合格") ? "#2C7A4E" : "#9E3A38"
			} }, meta.grade), (0, react.createElement)("span", { style: {
				opacity: .6,
				fontSize: "0.85em"
			} }, `异常 ${problems.length} 项 · 未评定 ${unavailable.length} 项`)), problems.length > 0 && (0, react.createElement)("div", { style: {
				display: "flex",
				flexDirection: "column",
				gap: "0.75em"
			} }, problems.map((p, i) => (0, react.createElement)("div", {
				key: `${p.feature}-${i}`,
				style: {
					borderLeft: `3px solid ${tone(p.level)}`,
					paddingLeft: "0.85em",
					display: "flex",
					flexDirection: "column",
					gap: "0.15em"
				}
			}, (0, react.createElement)("div", { style: {
				display: "flex",
				gap: "0.6em",
				alignItems: "baseline"
			} }, (0, react.createElement)("span", { style: {
				color: tone(p.level),
				fontSize: "0.85em"
			} }, `[${p.level}]`), (0, react.createElement)("strong", null, p.feature), p.value !== void 0 && (0, react.createElement)("span", { style: { opacity: .7 } }, `= ${p.value}${p.unit ?? ""}`)), field("判定", p.verdict), field("原因分析", p.cause), field("影响评估", p.impact), field("处理建议", p.action)))), unavailable.length > 0 && (0, react.createElement)("div", { style: {
				border: "1px dashed currentColor",
				opacity: .85,
				padding: "0.6em 0.85em",
				display: "flex",
				flexDirection: "column",
				gap: "0.25em"
			} }, (0, react.createElement)("div", { style: {
				fontSize: "0.85em",
				opacity: .7
			} }, "未评定（输入不足，不代表合格）"), unavailable.map((u, i) => (0, react.createElement)("div", { key: `${u.feature}-${i}` }, (0, react.createElement)("strong", null, u.feature), "：", u.reason))), problems.length === 0 && unavailable.length === 0 && (0, react.createElement)("div", { style: { opacity: .7 } }, "没有异常项，也没有未评定项。"));
		}
		//#endregion
		//#region lib/types/client/api.js
		/**
		* Browser-side reads over the Host's same-origin bridge.
		*
		* Everything goes through `/rlab/api/...` on the page's own origin. The compute
		* sidecar is never addressed directly: it has no authentication, and in the
		* deployed shape the browser can only reach the gateway anyway.
		*
		* Reads only, by construction — the bridge refuses writes. Anything that
		* changes state is a tool call, so it lands in the session log where it can be
		* replayed and audited. A button that quietly mutated data outside that log
		* would break the product's own traceability claim.
		*
		* @module
		*/
		/** A read that failed, carrying enough to tell the reader what to do about it. */
		var ApiError = class extends Error {
			status;
			constructor(message, status) {
				super(message);
				this.status = status;
				this.name = "ApiError";
			}
		};
		async function get(path, signal) {
			const res = await fetch(`/rlab/api${path}`, {
				signal: signal ?? null,
				headers: { accept: "application/json" }
			});
			const text = await res.text();
			if (!res.ok) {
				let detail = text.slice(0, 200);
				try {
					const parsed = JSON.parse(text);
					if (typeof parsed.detail === "string") detail = parsed.detail;
					else if (typeof parsed.error === "string") detail = parsed.error;
				} catch {}
				throw new ApiError(detail || `HTTP ${res.status}`, res.status);
			}
			return JSON.parse(text);
		}
		const api = {
			datasets: (signal) => get("/datasets", signal),
			dataset: (id, signal) => get(`/datasets/${id}`, signal),
			preview: (id, limit, signal) => get(`/datasets/${id}/preview?limit=${limit}`, signal),
			algorithms: (signal) => get("/algorithms", signal)
		};
		//#endregion
		//#region lib/types/client/views/DatasetsView.js
		/**
		* The dataset view: a lineage tree, not a list.
		*
		* The methodology this product settled on is that **data is a lineage DAG**.
		* A flat list of names loses the one fact that makes a derived number
		* trustworthy — where it came from and what was done to it. So sources are
		* roots, derived datasets nest under their parent, and each edge is labelled
		* with the operation that created it.
		*
		* Read-only on purpose. Running an algorithm from here would mutate state
		* outside the session log; that belongs to a tool call.
		*/
		/** Build the forest: sources are roots, derived nest under their parent. */
		function buildForest(rows) {
			const byId = /* @__PURE__ */ new Map();
			for (const ds of rows) byId.set(ds.id, {
				ds,
				children: []
			});
			const roots = [];
			for (const node of byId.values()) {
				const parentId = node.ds.derived_from;
				const parent = parentId === null ? void 0 : byId.get(parentId);
				if (parent === void 0) roots.push(node);
				else parent.children.push(node);
			}
			const byIdDesc = (a, b) => b.ds.id - a.ds.id;
			roots.sort(byIdDesc);
			for (const n of byId.values()) n.children.sort(byIdDesc);
			return roots;
		}
		function opLabel(ds) {
			const op = ds.lineage?.op;
			if (op === void 0) return null;
			return op.label ?? op.slug ?? null;
		}
		function Row({ node, depth, selected, onSelect }) {
			const { ds } = node;
			const isSel = selected === ds.id;
			const op = opLabel(ds);
			return (0, react.createElement)("div", null, (0, react.createElement)("button", {
				type: "button",
				onClick: () => onSelect(ds.id),
				"data-rlab-dataset": String(ds.id),
				"data-rlab-depth": String(depth),
				style: {
					display: "flex",
					alignItems: "baseline",
					gap: "0.5em",
					width: "100%",
					textAlign: "left",
					background: isSel ? "rgba(127,127,127,0.16)" : "transparent",
					border: "none",
					borderLeft: `2px solid ${isSel ? "currentColor" : "transparent"}`,
					padding: "0.35em 0.6em",
					paddingLeft: `${.6 + depth * 1.1}em`,
					color: "inherit",
					font: "inherit",
					cursor: "pointer"
				}
			}, (0, react.createElement)("span", { style: {
				opacity: .68,
				fontVariantNumeric: "tabular-nums"
			} }, `#${ds.id}`), (0, react.createElement)("span", { style: {
				flex: 1,
				minWidth: 0,
				overflow: "hidden",
				textOverflow: "ellipsis",
				whiteSpace: "nowrap"
			} }, ds.name), op !== null && (0, react.createElement)("span", {
				style: {
					opacity: .78,
					fontSize: "0.82em",
					flex: "none"
				},
				title: "产生这个数据集的算法"
			}, op), (0, react.createElement)("span", { style: {
				opacity: .62,
				fontSize: "0.82em",
				flex: "none",
				fontVariantNumeric: "tabular-nums"
			} }, `${ds.rows}×${ds.columns}`)), node.children.map((c) => (0, react.createElement)(Row, {
				key: c.ds.id,
				node: c,
				depth: depth + 1,
				selected,
				onSelect
			})));
		}
		function PreviewPane({ id }) {
			const [data, setData] = (0, react.useState)(null);
			const [error, setError] = (0, react.useState)(null);
			(0, react.useEffect)(() => {
				if (id === null) {
					setData(null);
					setError(null);
					return;
				}
				const ac = new AbortController();
				setData(null);
				setError(null);
				api.preview(id, 50, ac.signal).then(setData).catch((e) => {
					if (e.name !== "AbortError") setError(e.message);
				});
				return () => ac.abort();
			}, [id]);
			if (id === null) return (0, react.createElement)("div", { style: {
				opacity: .6,
				padding: "1em"
			} }, "选择左侧的数据集查看内容。");
			if (error !== null) return (0, react.createElement)("div", { style: {
				padding: "1em",
				color: "#b4544f"
			} }, `读取失败：${error}`);
			if (data === null) return (0, react.createElement)("div", { style: {
				opacity: .6,
				padding: "1em"
			} }, "读取中…");
			if (data.rows.length === 0) return (0, react.createElement)("div", { style: {
				opacity: .6,
				padding: "1em"
			} }, "（无数据行）");
			return (0, react.createElement)("div", { style: {
				overflow: "auto",
				height: "100%"
			} }, (0, react.createElement)("table", { style: {
				borderCollapse: "collapse",
				fontSize: "0.86em",
				width: "100%"
			} }, (0, react.createElement)("thead", null, (0, react.createElement)("tr", null, data.columns.map((c) => (0, react.createElement)("th", {
				key: c,
				style: {
					textAlign: "left",
					padding: "0.3em 0.7em",
					position: "sticky",
					top: 0,
					background: "var(--dsh-surface, rgba(127,127,127,0.12))",
					borderBottom: "1px solid rgba(127,127,127,0.35)",
					whiteSpace: "nowrap"
				}
			}, c)))), (0, react.createElement)("tbody", null, data.rows.map((r, i) => (0, react.createElement)("tr", { key: i }, data.columns.map((c) => (0, react.createElement)("td", {
				key: c,
				style: {
					padding: "0.25em 0.7em",
					borderBottom: "1px solid rgba(127,127,127,0.15)",
					fontVariantNumeric: "tabular-nums",
					whiteSpace: "nowrap"
				}
			}, r[c] === null || r[c] === void 0 ? "" : String(r[c]))))))));
		}
		function DatasetsView() {
			const [rows, setRows] = (0, react.useState)(null);
			const [error, setError] = (0, react.useState)(null);
			const [selected, setSelected] = (0, react.useState)(null);
			(0, react.useEffect)(() => {
				const ac = new AbortController();
				api.datasets(ac.signal).then((d) => {
					setRows(d);
					setSelected((s) => s ?? d[0]?.id ?? null);
				}).catch((e) => {
					if (e.name !== "AbortError") setError(e.message);
				});
				return () => ac.abort();
			}, []);
			const forest = (0, react.useMemo)(() => buildForest(rows ?? []), [rows]);
			if (error !== null) return (0, react.createElement)("div", { style: {
				padding: "1.5em",
				color: "#b4544f"
			} }, `读取数据集失败：${error}`);
			if (rows === null) return (0, react.createElement)("div", { style: {
				padding: "1.5em",
				opacity: .6
			} }, "读取中…");
			if (rows.length === 0) return (0, react.createElement)("div", { style: {
				padding: "1.5em",
				opacity: .7
			} }, "还没有数据集。在对话里让 agent 用 dataset_ingest 导入一个文件。");
			return (0, react.createElement)("div", { style: {
				display: "grid",
				gridTemplateColumns: "minmax(260px, 34%) 1fr",
				height: "100%",
				minHeight: 0
			} }, (0, react.createElement)("div", { style: {
				overflow: "auto",
				borderRight: "1px solid rgba(127,127,127,0.25)",
				padding: "0.4em 0"
			} }, forest.map((n) => (0, react.createElement)(Row, {
				key: n.ds.id,
				node: n,
				depth: 0,
				selected,
				onSelect: setSelected
			}))), (0, react.createElement)("div", { style: {
				minWidth: 0,
				minHeight: 0
			} }, (0, react.createElement)(PreviewPane, { id: selected })));
		}
		//#endregion
		//#region lib/types/client/views/AlgorithmsView.js
		/**
		* The algorithm catalogue.
		*
		* Provenance is the column that matters. The product's premise is "vetted
		* classical algorithms first, sandboxed user code second, model-written code
		* last" — so where an algorithm came from, and whether it passed a test, are
		* shown next to its name rather than buried in a detail pane. An unverified
		* AI-written algorithm sitting unmarked beside a citable classical one would
		* undo the distinction the product is built on.
		*/
		const SOURCE_LABEL = {
			builtin: "内置",
			user: "用户上传",
			ai: "AI 生成"
		};
		function Badge({ source, verified }) {
			const untested = source !== "builtin" && !verified;
			return (0, react.createElement)("span", { style: {
				color: source === "builtin" ? "#2C7A4E" : untested ? "#9E3A38" : "#8F6318",
				border: "1px solid currentColor",
				borderRadius: "2px",
				padding: "0 0.4em",
				fontSize: "0.78em",
				whiteSpace: "nowrap",
				flex: "none"
			} }, SOURCE_LABEL[source] ?? source, untested ? " · 未通过测试" : "");
		}
		function AlgorithmsView() {
			const [rows, setRows] = (0, react.useState)(null);
			const [error, setError] = (0, react.useState)(null);
			const [category, setCategory] = (0, react.useState)("");
			const [query, setQuery] = (0, react.useState)("");
			(0, react.useEffect)(() => {
				const ac = new AbortController();
				api.algorithms(ac.signal).then(setRows).catch((e) => {
					if (e.name !== "AbortError") setError(e.message);
				});
				return () => ac.abort();
			}, []);
			const categories = (0, react.useMemo)(() => [...new Set((rows ?? []).map((a) => a.category))].sort(), [rows]);
			const shown = (0, react.useMemo)(() => {
				const q = query.trim().toLowerCase();
				return (rows ?? []).filter((a) => (category === "" || a.category === category) && (q === "" || a.slug.toLowerCase().includes(q) || a.name.toLowerCase().includes(q) || a.description.toLowerCase().includes(q)));
			}, [
				rows,
				category,
				query
			]);
			if (error !== null) return (0, react.createElement)("div", { style: {
				padding: "1.5em",
				color: "#b4544f"
			} }, `读取算法失败：${error}`);
			if (rows === null) return (0, react.createElement)("div", { style: {
				padding: "1.5em",
				opacity: .6
			} }, "读取中…");
			return (0, react.createElement)("div", { style: {
				display: "flex",
				flexDirection: "column",
				height: "100%",
				minHeight: 0
			} }, (0, react.createElement)("div", { style: {
				display: "flex",
				gap: "0.6em",
				padding: "0.6em 0.9em",
				flexWrap: "wrap",
				borderBottom: "1px solid rgba(127,127,127,0.25)",
				alignItems: "center"
			} }, (0, react.createElement)("input", {
				type: "search",
				value: query,
				placeholder: "搜索算法",
				onChange: (e) => setQuery(e.target.value),
				style: {
					flex: "1 1 12em",
					minWidth: "8em",
					padding: "0.3em 0.6em",
					background: "transparent",
					color: "inherit",
					font: "inherit",
					border: "1px solid rgba(127,127,127,0.4)",
					borderRadius: "3px"
				}
			}), (0, react.createElement)("select", {
				value: category,
				onChange: (e) => setCategory(e.target.value),
				style: {
					padding: "0.3em 0.5em",
					background: "transparent",
					color: "inherit",
					font: "inherit",
					border: "1px solid rgba(127,127,127,0.4)",
					borderRadius: "3px"
				}
			}, (0, react.createElement)("option", { value: "" }, `全部分类（${rows.length}）`), categories.map((c) => (0, react.createElement)("option", {
				key: c,
				value: c
			}, c)))), (0, react.createElement)("div", { style: {
				overflow: "auto",
				flex: 1,
				minHeight: 0
			} }, shown.length === 0 ? (0, react.createElement)("div", { style: {
				padding: "1.5em",
				opacity: .65
			} }, "没有匹配的算法。") : shown.map((a) => (0, react.createElement)("div", {
				key: `${a.source}:${a.slug}`,
				"data-rlab-algo": a.slug,
				"data-rlab-source": a.source,
				style: {
					padding: "0.55em 0.9em",
					borderBottom: "1px solid rgba(127,127,127,0.15)",
					display: "flex",
					flexDirection: "column",
					gap: "0.15em"
				}
			}, (0, react.createElement)("div", { style: {
				display: "flex",
				gap: "0.6em",
				alignItems: "baseline"
			} }, (0, react.createElement)("code", { style: { fontSize: "0.9em" } }, a.slug), (0, react.createElement)("span", { style: {
				flex: 1,
				minWidth: 0
			} }, a.name), (0, react.createElement)("span", { style: {
				opacity: .72,
				fontSize: "0.82em",
				flex: "none"
			} }, a.category), (0, react.createElement)(Badge, {
				source: a.source,
				verified: a.verified === true
			})), a.description ? (0, react.createElement)("div", { style: {
				opacity: .78,
				fontSize: "0.86em"
			} }, a.description) : null))));
		}
		//#endregion
		//#region lib/types/client/Workbench.js
		/**
		* The workbench: RLab's own surface inside the harness shell.
		*
		* dsh's frame is deliberately chat-centric — `sidebar` and `conversation` are
		* single-occupancy slots, so registering into either would REPLACE the shell's
		* own column rather than add to it. `shell.overlay` is the one seat documented
		* as additive ("a frame-wide surface of your own"), so that is where a product
		* with its own views belongs.
		*
		* The layer is click-through by default; only the launcher and the open panel
		* take pointer events, so the conversation underneath stays fully usable when
		* the workbench is closed.
		*/
		const TABS = [{
			id: "datasets",
			label: "数据集",
			render: () => (0, react.createElement)(DatasetsView)
		}, {
			id: "algorithms",
			label: "算法库",
			render: () => (0, react.createElement)(AlgorithmsView)
		}];
		/** Shared surface colour, resolved from the host theme with a readable fallback. */
		const SURFACE = "var(--dsh-color-surface, var(--dsh-surface, #17191a))";
		function Workbench() {
			const [open, setOpen] = (0, react.useState)(false);
			const [tab, setTab] = (0, react.useState)("datasets");
			(0, react.useEffect)(() => {
				if (!open) return;
				const onKey = (e) => {
					if (e.key === "Escape") setOpen(false);
				};
				window.addEventListener("keydown", onKey);
				return () => window.removeEventListener("keydown", onKey);
			}, [open]);
			if (!open) return (0, react.createElement)("button", {
				type: "button",
				onClick: () => setOpen(true),
				title: "RLab 工作台：数据集与算法库",
				style: {
					position: "absolute",
					right: "1rem",
					bottom: "1rem",
					pointerEvents: "auto",
					padding: "0.45em 0.9em",
					borderRadius: "999px",
					cursor: "pointer",
					background: SURFACE,
					color: "inherit",
					font: "inherit",
					border: "1px solid rgba(127,127,127,0.45)",
					boxShadow: "0 2px 10px rgba(0,0,0,0.25)"
				}
			}, "工作台");
			const active = TABS.find((t) => t.id === tab) ?? TABS[0];
			return (0, react.createElement)("div", { style: {
				position: "absolute",
				inset: 0,
				pointerEvents: "auto",
				background: SURFACE,
				display: "flex",
				flexDirection: "column",
				borderTop: "1px solid rgba(127,127,127,0.3)"
			} }, (0, react.createElement)("div", { style: {
				display: "flex",
				alignItems: "center",
				gap: "0.4em",
				padding: "0.5em 0.9em",
				borderBottom: "1px solid rgba(127,127,127,0.25)"
			} }, (0, react.createElement)("strong", { style: { marginRight: "0.6em" } }, "RLab 工作台"), TABS.map((t) => (0, react.createElement)("button", {
				key: t.id,
				type: "button",
				onClick: () => setTab(t.id),
				style: {
					padding: "0.28em 0.75em",
					cursor: "pointer",
					font: "inherit",
					color: "inherit",
					borderRadius: "3px",
					background: t.id === tab ? "rgba(127,127,127,0.2)" : "transparent",
					border: `1px solid ${t.id === tab ? "rgba(127,127,127,0.45)" : "transparent"}`
				}
			}, t.label)), (0, react.createElement)("span", { style: { flex: 1 } }), (0, react.createElement)("span", { style: {
				opacity: .5,
				fontSize: "0.8em",
				marginRight: "0.6em"
			} }, "只读视图"), (0, react.createElement)("button", {
				type: "button",
				onClick: () => setOpen(false),
				title: "关闭（Esc）",
				style: {
					padding: "0.28em 0.7em",
					cursor: "pointer",
					font: "inherit",
					color: "inherit",
					background: "transparent",
					border: "1px solid rgba(127,127,127,0.4)",
					borderRadius: "3px"
				}
			}, "关闭")), (0, react.createElement)("div", { style: {
				flex: 1,
				minHeight: 0
			} }, active.render()));
		}
		//#endregion
		//#region lib/types/client/index.js
		/**
		* RLab Cortex browser half: keyed tool views for the data-analysis tools.
		*
		* The generic tool row prints whatever text a tool rendered. That is fine for a
		* shell command, but it flattens the two things this product exists to keep
		* distinct: a finding that was *assessed and failed* versus an item that could
		* *not be assessed at all*. A wall of text lets 未评定 read like a pass, which
		* is precisely the failure mode the wind-tunnel module was built to prevent.
		*
		* So these views are not decoration. They encode, in form, the distinction the
		* domain refuses to blur.
		*
		* Views are pure functions of the durable call/result slice, so they replay
		* identically from the session log and never consult live services.
		*
		* @module
		*/
		/** Required services: the keyed tool-view registry. */
		const inject = ["slots"];
		/**
		* Register the keyed tool views.
		*
		* Both keys name tools this product registered itself, so registration is
		* purely additive — nothing shipped by dsh is taken over.
		*/
		function apply(ctx) {
			ctx.slots.inject("tool.call.toolview", () => ctx.slots.register({
				name: "tool.call.toolview",
				key: "algo_run"
			}, AlgoRunRow));
			ctx.slots.inject("tool.call.toolview", () => ctx.slots.register({
				name: "tool.call.toolview",
				key: "wt_findings"
			}, WtFindingsRow));
			ctx.slots.inject("shell.overlay", () => ctx.slots.register({
				name: "shell.overlay",
				id: "rlab-workbench"
			}, Workbench));
		}
		//#endregion
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});

//# sourceMappingURL=client.js.map