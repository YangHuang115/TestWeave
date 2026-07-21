import "@testweave/ui/styles.css";

import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { router } from "./app/router";
import "./styles/base.css";

createApp(App).use(createPinia()).use(router).mount("#app");
