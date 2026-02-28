import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider, createTheme } from "@mantine/core";
import {
  CodeHighlightAdapterProvider,
  createHighlightJsAdapter,
} from "@mantine/code-highlight";
import hljs from "highlight.js/lib/core";
import json from "highlight.js/lib/languages/json";
import yaml from "highlight.js/lib/languages/yaml";
import plaintext from "highlight.js/lib/languages/plaintext";
import "@mantine/core/styles.css";
import "@mantine/code-highlight/styles.css";
import "highlight.js/styles/github.css";
import App from "./App";
import "./App.css";

hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("plaintext", plaintext);
const highlightJsAdapter = createHighlightJsAdapter(hljs);

const theme = createTheme({
  fontFamily:
    '"Barlow", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif',
  primaryColor: "yellow",
  colors: {
    yellow: [
      "#FFF9E0", "#FFF3C4", "#FFEC99", "#FFE066",
      "#FFD43B", "#FEC62E", "#F59F00", "#E67700",
      "#D9780F", "#C2680A",
    ],
  },
});

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <CodeHighlightAdapterProvider adapter={highlightJsAdapter}>
        <App />
      </CodeHighlightAdapterProvider>
    </MantineProvider>
  </StrictMode>,
);
