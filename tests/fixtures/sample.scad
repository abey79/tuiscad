// Sample fixture for parser/preset tests.

// X dimension. units or mm.
Width = [3, 0]; //0.1
// Toggle the magic
enable_magic = false;
mode = "auto"; //[auto, manual, off]
position = "center"; //[near:"← left", center:"↔ center", far:"→ right"]
weight = 1.5; //[0:0.1:10]
items = 5; //[1:10]

/* [Advanced] */
pitch = [42, 42, 7]; //[0:1:9999]
// Custom grid weighting (nested vector — not editable element-by-element)
xpos1 = [3, [2, [3, 3]], 0, 2, 4, 0];

/* [Hidden] */
secret = "hidden value";

module after_customizer() {}
ignored = 42;
