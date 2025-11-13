// -------------------------------------------------------
// FULL AUTOMATION PIPELINE - PHASE 1–6
// Batch Music Video Builder + Renderer (FINAL FIXED)
// -------------------------------------------------------
// Usage:
//  1) Run main.py to build /jobs/job_001 → job_012
//  2) Open AE project with folders Foreground, Background,
//     OUTPUT1–OUTPUT12, and comps MAIN, LYRIC FONT N, Assets N, etc.
//  3) File → Scripts → Run Script File → select this file
//  4) Pick the /jobs folder → items import + comps wired + queued
// -------------------------------------------------------

// -----------------------------
// JSON Polyfill (for older AE)
// -----------------------------
if (typeof JSON === "undefined") {
    JSON = {};
    JSON.parse = function (s) {
        try { return eval("(" + s + ")"); }
        catch (e) { alert("Error parsing JSON: " + e.toString()); return null; }
    };
    JSON.stringify = function (obj) {
        var t = typeof obj;
        if (t !== "object" || obj === null) {
            if (t === "string") obj = '"' + obj + '"';
            return String(obj);
        } else {
            var n, v, json = [], arr = (obj && obj.constructor === Array);
            for (n in obj) {
                v = obj[n];
                t = typeof v;
                if (t === "string") v = '"' + v + '"';
                else if (t === "object" && v !== null) v = JSON.stringify(v);
                json.push((arr ? "" : '"' + n + '":') + String(v));
            }
            return (arr ? "[" : "{") + String(json) + (arr ? "]" : "}");
        }
    };
}


// -----------------------------
// MAIN
// -----------------------------
function main() {
    app.beginUndoGroup("Batch Music Video Build");

    var jobsFolder = Folder.selectDialog("Select your /jobs folder");
    if (!jobsFolder) return;

    var subfolders = jobsFolder.getFiles(function (f) { return f instanceof Folder; });
    var jsonFiles = [];
    for (var i = 0; i < subfolders.length; i++) {
        var files = subfolders[i].getFiles("*.json");
        if (files.length > 0) jsonFiles.push(files[0]);
    }
    if (jsonFiles.length === 0) {
        alert("No job_data.json files found inside subfolders of " + jobsFolder.fsName);
        return;
    }

    for (var j = 0; j < jsonFiles.length; j++) {
        var jobFile = jsonFiles[j];
        if (!jobFile.exists || !jobFile.open("r")) continue;
        var jsonText = jobFile.read();
        jobFile.close();
        if (!jsonText) continue;

        var jobData;
        try { jobData = JSON.parse(jsonText); }
        catch (e) { alert("Error parsing " + jobFile.name + ": " + e.toString()); continue; }

        jobData.audio_trimmed = toAbsolute(jobData.audio_trimmed);
        jobData.cover_image   = toAbsolute(jobData.cover_image);
        jobData.lyrics_file   = toAbsolute(jobData.lyrics_file);
        jobData.job_folder    = toAbsolute(jobData.job_folder);

        $.writeln("──────── Job " + jobData.job_id + " ────────");

        var audioFile = new File(jobData.audio_trimmed);
        var imageFile = new File(jobData.cover_image);
        if (!audioFile.exists) { alert(" Missing audio:\n" + jobData.audio_trimmed); continue; }
        if (!imageFile.exists) { alert(" Missing image:\n" + jobData.cover_image); continue; }

        // Duplicate MAIN
        var template = findCompByName("MAIN");
        var newComp = template.duplicate();
        newComp.name = "MV_JOB_" + ("00" + jobData.job_id).slice(-3);

        // Move duplicated comp into correct OUTPUT folder
        moveItemToFolder(newComp, "OUTPUT" + jobData.job_id);

        // Relink existing imported assets instead of replacing
        relinkFootageInsideOutputFolder(jobData.job_id, jobData.audio_trimmed, jobData.cover_image);

        autoResizeCoverInOutput(jobData.job_id);
        setWorkAreaToAudioDuration(jobData.job_id);
        updateSongTitle(jobData.job_id, jobData.song_title);


        applyColorsToBackground(jobData.job_id, jobData.colors);
        applyColorsWherePresent(newComp, jobData.colors);


        // Lyrics
        var outputComp, lyricComp;
        try { outputComp = findCompByName("OUTPUT " + jobData.job_id); }
        catch (e) { $.writeln(" Missing OUTPUT " + jobData.job_id + " — skipping job."); continue; }
        try { lyricComp = findCompByName("LYRIC FONT " + jobData.job_id); }
        catch (e) { $.writeln(" Missing LYRIC FONT " + jobData.job_id + " — skipping job."); continue; }

        var parsed = parseLyricsFile(jobData.lyrics_file);
        pushLyricsToCarousel(lyricComp, parsed.linesArray);
        setAudioMarkersFromTArray(lyricComp, parsed.tAndText);

        // Album art
        try {
            var assetsComp = findCompByName("Assets " + jobData.job_id);
            retargetImageLayersToFootage(assetsComp, "COVER");
            $.writeln(" Album art retargeted to COVER for job " + jobData.job_id);
        } catch (e) {
            $.writeln(" Assets " + jobData.job_id + " not found — skipping album art.");
        }


        // Add to render queue
        try {
            var renderPath = addToRenderQueue(outputComp, jobData.job_folder, jobData.job_id);
            $.writeln(" Queued: " + renderPath);
        } catch (e) {
            $.writeln(" Render queue error: " + e);
        }
    }

    alert(" All jobs queued. Review in Render Queue, then click Render.");
    app.endUndoGroup();
}


// -----------------------------
// Helper Functions
// -----------------------------

function findFolderByName(name) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FolderItem && it.name === name) return it;
    }
    return null;
}

function moveItemToFolder(item, folderName) {
    var folder = findFolderByName(folderName);
    if (folder) item.parentFolder = folder;
}

function toAbsolute(p) {
    if (!p) return p;
    p = p.replace(/\\/g, "/");
    var f = new File(p);
    if (!f.exists) {
        var base = File($.fileName).parent.parent;
        f = new File(base.fsName + "/" + p);
    }
    return f.fsName.replace(/\\/g, "/");
}

function applyColorsToBackground(jobId, colors) {
    if (!colors || !colors.length) return;
    var bgName = "BACKGROUND " + jobId;
    var bgComp;
    try { bgComp = findCompByName(bgName); } catch (_) { return; }

    // Find the exact layer named "BG GRADIENT"
    var gradLayer = null;
    for (var i = 1; i <= bgComp.numLayers; i++) {
        var lyr = bgComp.layer(i);
        if (lyr && lyr.name && lyr.name.toUpperCase() === "BG GRADIENT") {
            gradLayer = lyr;
            break;
        }
    }

    if (!gradLayer) {
        $.writeln(" No 'BG GRADIENT' layer found in " + bgName);
        return;
    }

    // Apply the colors directly
    var success = set4ColorGradientOnLayer(gradLayer, colors);
    if (success) {
        $.writeln(" Applied colors to BG GRADIENT in " + bgName);
    } else {
        $.writeln(" BG GRADIENT has no 4-Color Gradient effect in " + bgName);
    }
}
function set4ColorGradientOnLayer(layer, colors) {
    if (!layer || !(layer instanceof AVLayer)) {
        $.writeln(" Invalid layer reference in set4ColorGradientOnLayer()");
        return false;
    }

    if (!colors || !colors.length) {
        $.writeln(" No colors provided for " + layer.name);
        return false;
    }

    var fxGroup = layer.property("ADBE Effect Parade");
    if (!fxGroup || fxGroup instanceof Error) {
        $.writeln(" Layer " + layer.name + " has no Effect Parade");
        return false;
    }

    // Find the 4-Color Gradient effect by multiple possible names
    var fx = null;
    for (var i = 1; i <= fxGroup.numProperties; i++) {
        var p = fxGroup.property(i);
        if (!p) continue;
        try {
            var nm = (p.name || "").toLowerCase();
            var match = p.matchName || "";
            if (
                nm.indexOf("4-color gradient") !== -1 ||
                nm.indexOf("4 color gradient") !== -1 ||
                match === "ADBE 4ColorGradient" ||
                match === "ADBE Four-Color Gradient"
            ) {
                fx = p;
                break;
            }
        } catch (err) {
            $.writeln(" Error checking property " + i + " on " + layer.name + ": " + err.toString());
        }
    }

    if (!fx || fx instanceof Error) {
        $.writeln(" No valid 4-Color Gradient effect found on layer: " + layer.name);
        return false;
    }

    $.writeln(" Found 4-Color Gradient on layer: " + layer.name);

    var changed = false;

    for (var j = 0; j < Math.min(colors.length, 4); j++) {
        var col = colors[j];
        if (!col || typeof col !== "string") continue;

        var rgb = hexToRGB(col);
        var prop = null;

        try {
            prop = fx.property("Color " + (j + 1));
        } catch (err) {
            $.writeln(" Failed to get Color " + (j + 1) + " on " + layer.name + ": " + err.toString());
            continue;
        }

        if (!prop || prop instanceof Error || !prop.setValue) {
            $.writeln(" Invalid Color " + (j + 1) + " property on " + layer.name);
            continue;
        }

        try {
            prop.setValue(rgb);
            changed = true;
            $.writeln(" Set Color " + (j + 1) + " on " + layer.name + " to " + colors[j]);
        } catch (err) {
            $.writeln(" Failed to set Color " + (j + 1) + " on " + layer.name + ": " + err.toString());
        }
    }

    if (changed)
        $.writeln(" Successfully applied colors to " + layer.name);
    else
        $.writeln(" No colors changed for " + layer.name);

    return changed;
}



function applyColorsWherePresent(comp, colors) {
    if (!comp || !colors || !colors.length) return;
    $.writeln(" Scanning " + comp.name + " for 4-Color Gradients…");

    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (!lyr.property("Effects")) continue;

        var fx = null;
        try { fx = lyr.property("Effects")("4-Color Gradient"); } catch (_) {}
        if (!fx) {
            try { fx = lyr.property("Effects")("4 Color Gradient"); } catch (_) {}
        }
        if (!fx) continue;

        // Apply the gradient colors
        try {
            for (var j = 0; j < Math.min(colors.length, 4); j++) {
                var col = colors[j];
                if (!col || typeof col !== "string") continue;
                var rgb = hexToRGB(col);
                var colorProp = fx.property("Color " + (j + 1));
                if (colorProp && colorProp.setValue) colorProp.setValue(rgb);
            }
            $.writeln(" Applied colors to " + lyr.name + " in " + comp.name);
        } catch (err) {
            $.writeln(" Could not update " + lyr.name + ": " + err.toString());
        }
    }
}


function hexToRGB(hex) {
    if (!hex || typeof hex !== "string") return [1, 1, 1];
    hex = hex.replace("#", "");
    try {
        return [
            parseInt(hex.substring(0, 2), 16) / 255,
            parseInt(hex.substring(2, 4), 16) / 255,
            parseInt(hex.substring(4, 6), 16) / 255
        ];
    } catch (e) { return [1, 1, 1]; }
}

function findCompByName(name) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof CompItem && it.name === name) return it;
    }
    throw new Error("Comp not found: " + name);
}

function readTextFile(p) {
    var f = new File(p);
    f.open("r");
    var t = f.read();
    f.close();
    return t;
}

function parseLyricsFile(p) {
    var raw = readTextFile(p);
    var data = JSON.parse(raw);
    var linesArray = [], tAndText = [];

    for (var i = 0; i < data.length; i++) {
        var cur = String(data[i].lyric_current || data[i].cur || "");
        var t   = Number(data[i].t || 0);

        // Python already chunked to ~25 chars and assigned timestamps.
        // Do NOT split again here.
        linesArray.push(cur);
        tAndText.push({ t: t, cur: cur });
    }
    return { linesArray: linesArray, tAndText: tAndText };
}


function wrapTwoLines(s, limit) {
    // make sure any literal "\\r" becomes a real carriage return first
    s = String(s).replace(/\\r/g, "\r");

    if (s.length <= limit) return s;

    // split at the last space before limit
    var cut = s.lastIndexOf(" ", limit);
    if (cut < 0) cut = limit; // no space found, hard cut
    return s.substring(0, cut) + "\r" + s.substring(cut + 1).replace(/^\s+/, "");
}


function replaceLyricArrayInLayer(layer, linesArray) {
    var MAX = 25; // visual wrap threshold

    var lines = [];
    for (var i = 0; i < linesArray.length; i++) {
        var l = wrapTwoLines(linesArray[i], MAX);
        l = String(l).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        lines.push('"' + l + '"');
    }

    var newBlock = "var lyrics = [\n" + lines.join(",\n") + "\n];";
    var prop = layer.property("Source Text");
    if (!prop) return;
    var expr = prop.expression || "";
    var re = /var\s+lyrics\s*=\s*\[[\s\S]*?\];/;
    prop.expression = re.test(expr) ? expr.replace(re, newBlock) : newBlock + "\n" + expr;
}


function pushLyricsToCarousel(comp, arr) {
    var names = ["LYRIC PREVIOUS", "LYRIC CURRENT", "LYRIC NEXT 1", "LYRIC NEXT 2"];
    for (var i = 0; i < names.length; i++) {
        var lyr = comp.layer(names[i]);
        if (lyr) replaceLyricArrayInLayer(lyr, arr);
    }
}

function clearAllMarkers(layer) {
    var mk = layer.property("Marker");
    if (!mk) return;
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);
}

function ensureAudioLayer(comp) {
    var lyr = comp.layer("AUDIO");
    if (lyr) return lyr;

    // Fallback: find the first AVLayer that has audio enabled
    for (var i = 1; i <= comp.numLayers; i++) {
        var L = comp.layer(i);
        if (L instanceof AVLayer && L.hasAudio) {
            // rename it so expressions looking for "AUDIO" keep working
            try { L.name = "AUDIO"; } catch (_) {}
            return L;
        }
    }
    return null;
}

function setAudioMarkersFromTArray(lyricComp, tAndText) {
    var audio = ensureAudioLayer(lyricComp);
    if (!audio) { $.writeln(" No AUDIO layer found in " + lyricComp.name); return; }

    var mk = audio.property("Marker");
    if (!mk) { $.writeln(" No Marker prop on AUDIO in " + lyricComp.name); return; }

    // Clear markers
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);

    var lastT = 0;
    for (var k = 0; k < tAndText.length; k++) {
        var t = Number(tAndText[k].t) || 0;
        var name = String(tAndText[k].cur || ("LYRIC_" + (k + 1)));
        try {
            mk.setValueAtTime(t, new MarkerValue(name));
            if (t > lastT) lastT = t;
        } catch (e) {
            $.writeln(" Marker set failed at " + t + "s: " + e.toString());
        }
    }
    if (lastT + 2 > lyricComp.duration) lyricComp.duration = lastT + 2;
}


function addToRenderQueue(comp, jobFolder, jobId) {
    var root = new Folder(jobFolder).parent;
    var renderDir = new Folder(root.fsName + "/renders");
    if (!renderDir.exists) renderDir.create();
    var outPath = renderDir.fsName + "/job_" + ("00" + jobId).slice(-3) + ".mp4";
    var outFile = new File(outPath);

    var rq = app.project.renderQueue.items.add(comp);
    try { rq.applyTemplate("Best Settings"); } catch (e) {}
    try { rq.outputModule(1).applyTemplate("H.264"); } catch (e) {}
    rq.outputModule(1).file = outFile;
    return outPath;
}

function splitLongLines(line, maxLen) {
    if (!line || typeof line !== "string") return [];
    var words = line.split(" ");
    var lines = [];
    var buffer = ""; // renamed from 'current' to avoid global shadowing issues

    for (var i = 0; i < words.length; i++) {
        var w = String(words[i]);
        if ((buffer + w).length > maxLen) {
            lines.push(buffer.replace(/^\s+|\s+$/g, "")); // manual trim
            buffer = w + " ";
        } else {
            buffer += w + " ";
        }
    }

    if (buffer.replace(/^\s+|\s+$/g, "").length > 0) {
        lines.push(buffer.replace(/^\s+|\s+$/g, ""));
    }

    return lines;
}

function replaceInAllComps(compName, layerName, newItem) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof CompItem && it.name.indexOf(compName) !== -1) {
            for (var j = 1; j <= it.numLayers; j++) {
                var lyr = it.layer(j);
                if (lyr.name === layerName && lyr.source) {
                    lyr.replaceSource(newItem, false);
                }
            }
        }
    }
}
// Relink a Project FootageItem by its *project-panel name* (keeps name & all uses)
function relinkFootageByName(itemName, newFilePath) {
    var newFile = new File(newFilePath);
    if (!newFile.exists) {
        $.writeln(" File not found: " + newFilePath);
        return;
    }
    var found = false;
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FootageItem && it.name.toUpperCase() === itemName.toUpperCase()) {
            try {
                it.replace(newFile);     // relink only, name stays the same
                found = true;
                $.writeln(" Relinked '" + it.name + "' to " + newFile.fsName);
            } catch (e) {
                $.writeln(" Could not relink '" + it.name + "': " + e.toString());
            }
        }
    }
    if (!found) $.writeln(" Footage named '" + itemName + "' not found in Project.");
}

// Auto-resize any COVER layer to fit comp safely (preserves aspect)
function autoResizeCoverInOutput(jobId) {
    var comp = null;
    try { comp = findCompByName("OUTPUT " + jobId); } catch (_) {}
    if (!comp) return;

    // Find any layer named COVER, or whose source is named COVER
    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (!(lyr instanceof AVLayer)) continue;

        var isCover = (lyr.name && lyr.name.toUpperCase() === "COVER") ||
                      (lyr.source && lyr.source.name && lyr.source.name.toUpperCase() === "COVER");
        if (!isCover) continue;

        var cw = comp.width, ch = comp.height;
        var lw = lyr.source && lyr.source.width, lh = lyr.source && lyr.source.height;
        if (!lw || !lh) continue;

        var scale = 100 * Math.min(cw / lw, ch / lh);
        try { lyr.property("Scale").setValue([scale, scale]); } catch (_) {}
        $.writeln(" Auto-resized COVER in " + comp.name);
    }
}

function retargetImageLayersToFootage(assetComp, footageName) {
    if (!assetComp) return;

    var coverFootage = null;
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FootageItem && it.name.toUpperCase() === footageName.toUpperCase()) {
            coverFootage = it;
            break;
        }
    }

    if (!coverFootage) {
        $.writeln(" Footage '" + footageName + "' not found.");
        return;
    }

    for (var L = 1; L <= assetComp.numLayers; L++) {
        var lyr = assetComp.layer(L);
        if (!(lyr instanceof AVLayer)) continue;
        if (!(lyr.source instanceof FootageItem)) continue;

        var srcName = (lyr.source.name || "").toLowerCase();
        var lyrName = (lyr.name || "").toLowerCase();

        // only target layers clearly meant to be the album art
        var isCoverLayer =
            lyrName === "cover" ||
            lyrName.indexOf("album") !== -1 ||
            lyrName.indexOf("art") !== -1 ||
            srcName === "cover" ||
            srcName.indexOf("album") !== -1;

        if (!isCoverLayer) continue;

        try {
            lyr.replaceSource(coverFootage, false); // keep transform, effects, etc.
            $.writeln(" Replaced album art layer '" + lyr.name + "' with COVER footage in " + assetComp.name);
        } catch (e) {
            $.writeln(" Could not replace '" + lyr.name + "': " + e.toString());
        }
    }
}

// Set comp work area to audio duration
function setWorkAreaToAudioDuration(jobId) {
    var comp = null;
    try { comp = findCompByName("LYRIC FONT " + jobId); } catch (_) {}
    if (!comp) return;

    // Look for the AUDIO footage used in this job’s Assets folder
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) return;

    var assetsFolder = null;
    for (var i = 1; i <= outputFolder.numItems; i++) {
        var it = outputFolder.item(i);
        if (it instanceof FolderItem && it.name.toUpperCase().indexOf("ASSETS OT") === 0) {
            assetsFolder = it; break;
        }
    }
    if (!assetsFolder) return;

    var audioFootage = null;
    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (it instanceof FootageItem && (it.name || "").toUpperCase() === "AUDIO") {
            audioFootage = it; break;
        }
    }
    if (!audioFootage || !audioFootage.duration) return;

    var dur = audioFootage.duration;
    comp.workAreaStart = 0;
    comp.workAreaDuration = dur;
    comp.duration = Math.max(comp.duration, dur);
    $.writeln(" Set work area for LYRIC FONT " + jobId + " to " + dur.toFixed(2) + "s");
}


// Update title text inside Assets comp
// Update the TOPMOST text layer inside "Assets N" to the provided title
function updateSongTitle(jobId, titleText) {
    if (!titleText) return;
    try {
        var assetsComp = findCompByName("Assets " + jobId);
        if (!assetsComp) { $.writeln(" Assets " + jobId + " not found."); return; }

        // Find the first layer that has a Source Text property (topmost text layer)
        var targetTextLayer = null;
        for (var i = 1; i <= assetsComp.numLayers; i++) {
            var lyr = assetsComp.layer(i);
            var txtProp = lyr.property("Source Text");
            if (txtProp) { targetTextLayer = lyr; break; }
        }

        if (!targetTextLayer) {
            $.writeln(" No text layer found in " + assetsComp.name);
            return;
        }

        var txtProp = targetTextLayer.property("Source Text");
        var doc = txtProp.value;       // TextDocument
        doc.text = String(titleText);  // supports \r for line breaks if you ever pass them
        txtProp.setValue(doc);

        $.writeln(" Set song title on layer '" + targetTextLayer.name +
                  "' in " + assetsComp.name + " to: " + titleText);
    } catch (e) {
        $.writeln(" Could not update title for job " + jobId + ": " + e.toString());
    }
}

function relinkFootageInsideOutputFolder(jobId, audioPath, coverPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln(" OUTPUT" + jobId + " folder not found.");
        return;
    }

    // Find the nested "Assets OTX" folder inside
    var assetsFolder = null;
    for (var i = 1; i <= outputFolder.numItems; i++) {
        var it = outputFolder.item(i);
        if (it instanceof FolderItem && it.name.toUpperCase().indexOf("ASSETS OT") === 0) {
            assetsFolder = it;
            break;
        }
    }

    if (!assetsFolder) {
        $.writeln(" Assets folder not found inside OUTPUT" + jobId);
        return;
    }

    var audioFile = new File(audioPath);
    var coverFile = new File(coverPath);
    if (!audioFile.exists || !coverFile.exists) {
        $.writeln(" Missing audio or cover file for job " + jobId);
        return;
    }

    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (!(it instanceof FootageItem)) continue;

        var name = (it.name || "").toUpperCase();
        try {
            if (name === "AUDIO") {
                it.replace(audioFile);
                $.writeln(" Replaced AUDIO inside Assets OT" + jobId);
            } else if (name === "COVER") {
                it.replace(coverFile);
                $.writeln(" Replaced COVER inside Assets OT" + jobId);
            }
        } catch (e) {
            $.writeln(" Could not relink " + it.name + ": " + e.toString());
        }
    }
}





// -----------------------------
main();
