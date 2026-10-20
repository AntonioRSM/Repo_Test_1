// Workspace S.r.l. brand for the DeepSeek Harness web client.
// Template: tools/build-plugins.mjs fills the asset placeholders with the official artwork
// (docs/manual/assets) and writes lib/client.js. Edit this file, then run `npm run build`.
//
// Brand guidelines v1.0 applied here:
// - logo at its minimum width of 200 px, positive on light and negative on dark backgrounds;
// - icon at its minimum of 48 px (conversation hero) and as favicon (the only allowed exception);
// - palette Azzurro #2E6BD6, Inchiostro #16181D, Grigio #6B6F78, Grigio chiaro #A4A7AF, Carta #F4F2EC;
// - Lexend 400 for text and 600 for headings.
window.__ModuleLoader__.load({
	id: "@workspace-sm/dsh-workspace-brand",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		const { jsx, jsxs } = require("react/jsx-runtime");

		const LOGO_POSITIVE = __LOGO_POSITIVE__;
		const LOGO_NEGATIVE = __LOGO_NEGATIVE__;
		const ICON_PNG = __ICON_PNG__;
		const LEXEND_WOFF2 = __LEXEND_WOFF2__;

		const PRODUCT = "Workspace Harness";
		const STYLE_ID = "wsos-brand-style";

		// Alias tokens of dsh-client-ui-theme, as { light, dark } pairs.
		const TOKENS = {
			"--dsw-alias-bg-base": { light: "#F4F2EC", dark: "#16181D" },
			"--dsw-alias-bg-layer-1": { light: "#FFFFFF", dark: "#1E2026" },
			"--dsw-alias-bg-layer-2": { light: "#ECE9E1", dark: "#262931" },
			"--dsw-alias-bg-overlay": { light: "#FFFFFF", dark: "#1E2026" },
			"--dsw-alias-border-l1": { light: "#E2DFD6", dark: "#2C2F37" },
			"--dsw-alias-border-l2": { light: "#CFCBC0", dark: "#3A3E47" },
			"--dsw-alias-brand-primary": { light: "#2E6BD6", dark: "#2E6BD6" },
			"--dsw-alias-label-primary": { light: "#16181D", dark: "#F4F2EC" },
			"--dsw-alias-label-secondary": { light: "#6B6F78", dark: "#A4A7AF" },
			"--dsw-specific-sidebar-fill": { light: "#ECE9E1", dark: "#121418" }
		};

		const CSS = `
@font-face { font-family: "Lexend"; font-style: normal; font-weight: 100 900; font-display: swap; src: url(${LEXEND_WOFF2}) format("woff2"); }
h1, h2, h3, h4, h5, h6, strong, b, th { font-weight: 600; }
.wsos-logo { display: block; width: 200px; min-width: 200px; height: auto; }
.wsos-logo-negative { display: none; }
body[data-ds-dark-theme] .wsos-logo-positive { display: none; }
body[data-ds-dark-theme] .wsos-logo-negative { display: block; }
.wsos-icon { display: block; width: 48px; height: 48px; }
`;

		function installStyle() {
			if (document.getElementById(STYLE_ID)) return () => {};
			const style = document.createElement("style");
			style.id = STYLE_ID;
			style.textContent = CSS;
			document.head.appendChild(style);
			return () => style.remove();
		}

		// Favicon: the guidelines allow the icon below 48 px only here (16–32 px).
		function installFavicon() {
			const previous = [...document.querySelectorAll('link[rel="icon"]')];
			previous.forEach((link) => link.remove());
			const link = document.createElement("link");
			link.rel = "icon";
			link.type = "image/png";
			link.href = ICON_PNG;
			document.head.appendChild(link);
			return () => {
				link.remove();
				previous.forEach((old) => document.head.appendChild(old));
			};
		}

		// The layout writes "<session> — DeepSeek Harness"; keep the session part, rename the product.
		function installTitle() {
			const rename = () => {
				if (document.title.includes("DeepSeek Harness")) document.title = document.title.replace("DeepSeek Harness", PRODUCT);
			};
			rename();
			const observer = new MutationObserver(rename);
			observer.observe(document.head, { subtree: true, childList: true, characterData: true });
			return () => observer.disconnect();
		}

		function WorkspaceLogo() {
			return jsxs("span", {
				title: PRODUCT,
				children: [
					jsx("img", { className: "wsos-logo wsos-logo-positive", src: LOGO_POSITIVE, alt: "workspace sm" }),
					jsx("img", { className: "wsos-logo wsos-logo-negative", src: LOGO_NEGATIVE, alt: "workspace sm" })
				]
			});
		}

		// The sidebar mark slot is 24 px, below the icon's 48 px minimum: it stays empty and the
		// logotype in the name slot carries the brand.
		function EmptyMark() {
			return null;
		}

		function WorkspaceIcon() {
			return jsx("img", { className: "wsos-icon", src: ICON_PNG, alt: "workspace sm" });
		}

		const inject = ["slots", "theme"];

		function apply(ctx) {
			ctx.effect(installStyle, "workspace-brand: style");
			ctx.effect(installFavicon, "workspace-brand: favicon");
			ctx.effect(installTitle, "workspace-brand: title");
			ctx.effect(() => ctx.theme.overrideTokens("workspace-brand", TOKENS), "workspace-brand: palette");
			ctx.slots.inject("sidebar.brand.mark", () => ctx.slots.inject("sidebar.brand.name", function* () {
				yield ctx.slots.register({ name: "sidebar.brand.mark" }, EmptyMark);
				yield ctx.slots.register({ name: "sidebar.brand.name" }, WorkspaceLogo);
			}));
			ctx.slots.inject("conversation.hero.brand.mark", () => ctx.slots.register({ name: "conversation.hero.brand.mark" }, WorkspaceIcon));
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
