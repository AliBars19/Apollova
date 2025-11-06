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
        if (!audioFile.exists) { alert("⚠️ Missing audio:\n" + jobData.audio_trimmed); continue; }
        if (!imageFile.exists) { alert("⚠️ Missing image:\n" + jobData.cover_image); continue; }

        // Import into correct folders
        var audioItem = app.project.importFile(new ImportOptions(audioFile));
        var imageItem = app.project.importFile(new ImportOptions(imageFile));
        moveItemToFolder(audioItem, "Background");
        moveItemToFolder(imageItem, "Foreground");

        // Duplicate MAIN
        var template = findCompByName("MAIN");
        var newComp = template.duplicate();
        newComp.name = "MV_JOB_" + ("00" + jobData.job_id).slice(-3);

        // Move duplicated comp into correct OUTPUT folder
        moveItemToFolder(newComp, "OUTPUT" + jobData.job_id);

        replaceLayer(newComp, "AUDIO", audioItem);
        replaceLayer(newComp, "COVER", imageItem);

        // Update BG colors (MAIN + BACKGROUND N)
        // safest: only set colors on BACKGROUND N → GRADIENT layer
        applyColorsToBackground(jobData.job_id, jobData.colors);

        // (optional) if you *also* want to recolor any 4-Color Gradient
        // that might exist inside the duplicated MAIN comp:
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
            replaceAlbumArt(assetsComp, imageItem);
            $.writeln(" Album art replaced for job " + jobData.job_id);
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

function replaceLayer(comp, name, newItem) {
    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (lyr.name === name) {
            try {
                // Store existing transform settings
                var pos = lyr.property("Transform")("Position").value;
                var scale = lyr.property("Transform")("Scale").value;
                var rot = lyr.property("Transform")("Rotation").value;
                var anchor = lyr.property("Transform")("Anchor Point").value;
                var parent = lyr.parent;

                // Replace source but keep transforms
                lyr.replaceSource(newItem, false);

                // Restore transform settings
                lyr.property("Transform")("Position").setValue(pos);
                lyr.property("Transform")("Scale").setValue(scale);
                lyr.property("Transform")("Rotation").setValue(rot);
                lyr.property("Transform")("Anchor Point").setValue(anchor);
                lyr.parent = parent;

                // Optional: auto-fit if it’s an image and size differs
                if (newItem.width && newItem.height && lyr.sourceRectAtTime) {
                    var rect = lyr.sourceRectAtTime(0, false);
                    var scaleX = (comp.width / rect.width) * 100;
                    var scaleY = (comp.height / rect.height) * 100;
                    var uniform = Math.min(scaleX, scaleY);
                    // comment this line out if you want *no auto-scaling*
                    // lyr.property("Transform")("Scale").setValue([uniform, uniform]);
                }

                $.writeln("Replaced layer '" + name + "' with " + newItem.name);
                return;
            } catch (err) {
                $.writeln(" Error replacing layer '" + name + "': " + err.toString());
                return;
            }
        }
    }
    $.writeln(" Layer not found: " + name + " in comp " + comp.name);
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
            // also handle "4 Color Gradient" (some AE versions differ)
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
        linesArray.push(cur);
        tAndText.push({ t: Number(data[i].t || 0), cur: cur });
    }
    return { linesArray: linesArray, tAndText: tAndText };
}

function replaceLyricArrayInLayer(layer, linesArray) {
    var lines = [];
    for (var i = 0; i < linesArray.length; i++) {
        var l = String(linesArray[i]).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
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

function setAudioMarkersFromTArray(comp, arr) {
    var audio = comp.layer("AUDIO");
    if (!audio) return;
    var mk = audio.property("Marker");
    if (!mk) return;
    clearAllMarkers(audio);
    var lastT = 0;
    for (var i = 0; i < arr.length; i++) {
        var mv = new MarkerValue(arr[i].cur || "LYRIC_" + (i + 1));
        mk.setValueAtTime(arr[i].t, mv);
        if (arr[i].t > lastT) lastT = arr[i].t;
    }
    if (lastT + 2 > comp.duration) comp.duration = lastT + 2;
}

function replaceAlbumArt(assetComp, newImage) {
    if (!assetComp) return;
    for (var i = 1; i <= assetComp.numLayers; i++) {
        var lyr = assetComp.layer(i);
        if (lyr && lyr.source && (lyr.source instanceof FootageItem)) {
            var n = (lyr.source.name || "").toLowerCase();
            if (n.indexOf(".jpg") !== -1 || n.indexOf(".png") !== -1) {
                lyr.replaceSource(newImage, false);
                return;
            }
        }
    }
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

// -----------------------------
main();
