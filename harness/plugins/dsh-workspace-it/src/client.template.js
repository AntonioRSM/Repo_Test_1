// Italian language pack for the DeepSeek Harness web client, registered through the public
// locale API (ctx.locale.addLanguage / ctx.locale.register) without touching DeepSeek packages.
// Template: tools/build-plugins.mjs inlines i18n/*.json into DICTIONARIES and writes lib/client.js.
window.__ModuleLoader__.load({
	id: "@workspace-sm/dsh-workspace-it",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

		// namespace -> { key: Italian text }, generated from i18n/<namespace>.json
		const DICTIONARIES = __DICTIONARIES__;

		const inject = ["locale"];

		function apply(ctx) {
			ctx.effect(() => ctx.locale.addLanguage({ id: "it", label: "Italiano", fallback: "en" }), "workspace-it: language");
			for (const [ns, dict] of Object.entries(DICTIONARIES)) {
				ctx.effect(() => ctx.locale.register(ns, "it", dict), `workspace-it: ${ns}`);
			}
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
