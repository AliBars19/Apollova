// Extracted pure functions from Apollova JSX files for testing
// (no AE-specific code — runs in standard Node.js)

function hexToRGB(hex) {
    if (!hex || typeof hex !== "string") return [1, 1, 1];
    hex = hex.replace("#", "");
    if (hex.length !== 6) return [1, 1, 1];
    try {
        var r = parseInt(hex.substring(0, 2), 16);
        var g = parseInt(hex.substring(2, 4), 16);
        var b = parseInt(hex.substring(4, 6), 16);
        if (isNaN(r) || isNaN(g) || isNaN(b)) return [1, 1, 1];
        return [r / 255, g / 255, b / 255];
    } catch (e) { return [1, 1, 1]; }
}

function sanitizeFilename(name) {
    if (!name) return "untitled";
    return String(name)
        .replace(/[\/\\:*?"<>|]/g, "")
        .replace(/\s+/g, " ")
        .replace(/^\s+|\s+$/g, "");
}

function buildSegmentsArrayStringWithEnds(markers) {
    var segmentStrings = [];
    for (var i = 0; i < markers.length; i++) {
        var m = markers[i];
        var t = Number(m.time) || 0;
        var e = Number(m.end_time) || (t + 5);
        var words = m.words || [];
        var wordStrings = [];
        for (var j = 0; j < words.length; j++) {
            var word = words[j];
            var w = String(word.word || "")
                .replace(/\\/g, "\\\\")
                .replace(/"/g, '\\"')
                .replace(/\r/g, "\\r")
                .replace(/\n/g, "\\n")
                .replace(/\t/g, "\\t");
            var s = Number(word.start) || 0;
            wordStrings.push('{w:"' + w + '",s:' + s.toFixed(3) + '}');
        }
        var segStr = '{t:' + t.toFixed(3) + ',e:' + e.toFixed(3) + ',words:[' + wordStrings.join(',') + ']}';
        segmentStrings.push(segStr);
    }
    return 'var segments = [\n    ' + segmentStrings.join(',\n    ') + '\n];';
}

// --- Run test case from CLI ---
var testCase = JSON.parse(process.argv[2]);
var fn = testCase.fn;
var args = testCase.args;
var result;

if (fn === 'hexToRGB') {
    result = hexToRGB(args[0]);
} else if (fn === 'sanitizeFilename') {
    result = sanitizeFilename(args[0]);
} else if (fn === 'buildSegmentsArrayStringWithEnds') {
    result = buildSegmentsArrayStringWithEnds(args[0]);
} else if (fn === 'evalSegments') {
    // Test that generated segment expression is syntactically valid
    try {
        var generated = buildSegmentsArrayStringWithEnds(args[0]);
        eval(generated);
        result = { valid: true, segmentCount: segments.length };
    } catch(e) { result = { valid: false, error: e.message }; }
} else if (fn === 'evalWordReveal') {
    // Simulate the Onyx word-reveal expression at a given time
    var generated = buildSegmentsArrayStringWithEnds(args[0]);
    eval(generated);
    var segIndex = args[1];  // 1-based
    var time = args[2];
    if (segIndex < 1 || segIndex > segments.length) {
        result = "";
    } else {
        var seg = segments[segIndex - 1];
        var output = "";
        var wordCount = 0;
        var wordsPerLine = 3;
        for (var i = 0; i < seg.words.length; i++) {
            if (time >= seg.words[i].s) {
                var word = seg.words[i].w;
                if (wordCount > 0) {
                    if (wordCount % wordsPerLine === 0) { output += "\r"; }
                    else { output += " "; }
                }
                output += word;
                wordCount++;
            }
        }
        result = output;
    }
} else {
    result = null;
}

console.log(JSON.stringify(result));
