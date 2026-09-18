# Pre-revision manuscript archive

This directory preserves the complete tracked state of Overleaf commit
`6b740e4ed7b529b54319f055fb28b4c56c448d6a` as pulled on 2026-09-18, before
the reader-facing wide-field solver revision.

`etex.sty` is the only added compatibility file. The bundled A&A class requires
that historical package name, while current pdfTeX already contains the e-TeX
primitives. It changes no manuscript content.

Build the archived main paper with:

```sh
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```
