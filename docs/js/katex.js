// KaTeX auto-render configuration.
//
// Deliberately currency-safe: neither `$` nor `$$` is registered as a math
// delimiter. This book's title contains "$7" and Appendix A is a full price
// list, so a dollar-based delimiter would silently turn prices into equations.
//
// Write math in backslash notation only:
//   inline   \( E = mc^2 \)
//   display  \[ \int_0^\infty e^{-x^2} dx \]
document.addEventListener("DOMContentLoaded", function () {
    renderMathInElement(document.body, {
        delimiters: [
            { left: "\\[", right: "\\]", display: true },
            { left: "\\(", right: "\\)", display: false }
        ],
        throwOnError: false
    });
});
