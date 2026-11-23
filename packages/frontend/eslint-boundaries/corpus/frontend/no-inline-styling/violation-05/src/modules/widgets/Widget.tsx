import { createElement } from "react";
import { Input } from "@terpjs/react-core";
import styles from "./Widget.module.css";

// A call carries the module class onto a framework control without any className attribute.
export const Widget = () => createElement(Input, { className: styles.board });
