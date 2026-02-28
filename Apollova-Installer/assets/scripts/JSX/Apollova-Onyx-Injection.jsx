// -------------------------------------------------------
// APOLLOVA ONYX - After Effects Automation
// Word-by-word lyrics with vinyl disc aesthetic
// -------------------------------------------------------
// Usage:
//  1) Run main_onyx.py to build /jobs/job_001 → job_012
//  2) Open AE project with OUTPUT1-12, PRE-OUTPUT, LYRIC FONT, etc.
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
            if (t === "string") obj = '"' + obj.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
            return String(obj);
        } else {
            var n, v, json = [], arr = (obj && obj.constructor === Array);
            for (n in obj) {
                v = obj[n];
                t = typeof v;
                if (t === "string") v = '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
                else if (t === "object" && v !== null) v = JSON.stringify(v);
                json.push((arr ? "" : '"' + n + '":') + String(v));
            }
            return (arr ? "[" : "{") + String(json) + (arr ? "]" : "}");
        }
    };
}


// -----------------------------
// INJECTED PATHS (replaced by GUI)
// -----------------------------
var JOBS_PATH = "{{JOBS_PATH}}";
var TEMPLATE_PATH = "{{TEMPLATE_PATH}}";
var AUTO_RENDER = "{{AUTO_RENDER}}";

// -----------------------------
// MAIN
// -----------------------------
function main() {
    // First, open the template project if path was injected
    if (TEMPLATE_PATH.indexOf("{{") === -1 && TEMPLATE_PATH !== "") {
        var templateFile = new File(TEMPLATE_PATH);
        if (templateFile.exists) {
            app.open(templateFile);
            $.writeln("Opened template: " + TEMPLATE_PATH);
        } else {
            alert("Template file not found:\n" + TEMPLATE_PATH);
            writeErrorLog("Template file not found: " + TEMPLATE_PATH);
            return;
        }
    }
    
    // Keep AE open after script runs (unless auto-render)
    if (AUTO_RENDER !== "true") {
        app.exitAfterLaunchAndEval = false;
    }
    
    app.beginUndoGroup("ONYX Batch Music Video Build");

    clearAllJobComps();

    // Clear render queue before adding new jobs
    for (var i = app.project.renderQueue.numItems; i >= 1; i--) {
        try { app.project.renderQueue.item(i).remove(); } catch (e) {}
    }
    $.writeln("Render queue cleared.");

    // Use injected path or fallback to prompt
    var jobsFolder;
    if (JOBS_PATH.indexOf("{{") === -1 && JOBS_PATH !== "") {
        jobsFolder = new Folder(JOBS_PATH);
    } else {
        jobsFolder = Folder.selectDialog("Select your /jobs folder (Apollova-Onyx/jobs)");
    }
    if (!jobsFolder || !jobsFolder.exists) {
        alert("Jobs folder not found: " + (JOBS_PATH || "not specified"));
        return;
    }

    var subfolders = jobsFolder.getFiles(function (f) { return f instanceof Folder; });
    var jsonFiles = [];
    
    for (var i = 0; i < subfolders.length; i++) {
        // Look for onyx_data.json in each job folder
        var files = subfolders[i].getFiles("onyx_data.json");
        if (files && files.length > 0) {
            jsonFiles.push(files[0]);
        }
    }
    
    if (jsonFiles.length === 0) {
        alert("No onyx_data.json files found inside subfolders of " + jobsFolder.fsName);
        return;
    }

    for (var j = 0; j < jsonFiles.length; j++) {
        var onyxFile = jsonFiles[j];
        if (!onyxFile.exists || !onyxFile.open("r")) continue;
        var onyxText = onyxFile.read();
        onyxFile.close();
        if (!onyxText) continue;

        var onyxData;
        try { onyxData = JSON.parse(onyxText); }
        catch (e) { alert("Error parsing " + onyxFile.name + ": " + e.toString()); continue; }

        // Get job folder from actual file location (reliable)
        var jobFolder = onyxFile.parent;
        
        // Also read job_data.json for paths and metadata
        var jobDataFile = new File(jobFolder.fsName + "/job_data.json");
        var jobData = {};
        
        if (jobDataFile.exists && jobDataFile.open("r")) {
            var jobDataText = jobDataFile.read();
            jobDataFile.close();
            try { jobData = JSON.parse(jobDataText); }
            catch (e) { $.writeln("Could not parse job_data.json"); }
        }

        // Convert paths to absolute WITH FALLBACKS
        jobData.audio_trimmed = toAbsolute(jobData.audio_trimmed) || (jobFolder.fsName + "/audio_trimmed.wav");
        jobData.cover_image = toAbsolute(jobData.cover_image) || (jobFolder.fsName + "/cover.jpg");
        jobData.job_folder = jobFolder.fsName.replace(/\\/g, "/");
        
        var jobId = jobData.job_id || (j + 1);
        var songTitle = jobData.song_title || "Unknown";
        var markers = onyxData.markers || [];
        var colors = jobData.colors || [];

        $.writeln("──────── ONYX Job " + jobId + " ────────");
        $.writeln("Song: " + songTitle);
        $.writeln("Markers: " + markers.length);

        var audioFile = new File(jobData.audio_trimmed);
        var coverFile = new File(jobData.cover_image);
        
        if (!audioFile.exists) { 
            alert("Missing audio:\n" + jobData.audio_trimmed); 
            continue; 
        }
        if (!coverFile.exists) {
            alert("Missing cover image:\n" + jobData.cover_image);
            continue;
        }

        // Duplicate MAIN template
        var template = findCompByName("MAIN");
        var newComp = template.duplicate();
        newComp.name = "ONYX_JOB_" + ("00" + jobId).slice(-3);

        // Move duplicated comp into correct OUTPUT folder
        moveItemToFolder(newComp, "OUTPUT" + jobId);

        // Relink audio and cover in Assets folder
        relinkFootageInsideOutputFolder(jobId, jobData.audio_trimmed, jobData.cover_image);
        
        // Set durations for all comps
        setAllCompDurations(jobId, jobData.audio_trimmed);
        
        // Update song title
        updateSongTitle(jobId, songTitle);

        // Apply background colors (4-Color Gradient like Aurora)
        if (colors && colors.length >= 2) {
            applyBackgroundColors(jobId, colors);
            $.writeln("Applied background colors for job " + jobId);
        }

        // Get LYRIC FONT comp (inside PRE-OUTPUT)
        var lyricComp;
        try { 
            lyricComp = findCompByName("LYRIC FONT " + jobId); 
        } catch (e) { 
            $.writeln("Missing LYRIC FONT " + jobId + " – skipping lyrics."); 
            continue; 
        }

        // Add markers to AUDIO layer in LYRIC FONT comp
        addOnyxMarkersToAudio(lyricComp, markers);
        
        // Inject word-by-word segments into LYRIC_TEXT expression (3 words per line)
        injectOnyxSegmentsToLyricText(lyricComp, markers);

        // Retarget album art in Assets comp
        try {
            var assetsComp = findCompByName("Assets " + jobId);
            retargetImageLayersToFootage(assetsComp, "COVER");
            $.writeln("Album art retargeted for job " + jobId);
        } catch (e) {
            $.writeln("Assets " + jobId + " not found – skipping album art.");
        }

        // Add to render queue
        try {
            var outputComp = findCompByName("OUTPUT " + jobId);
            var renderPath = addToRenderQueue(
                outputComp,
                jobData.job_folder,
                jobId,
                songTitle,
                "_ONYX"
            );
            $.writeln("Queued: " + renderPath);
        } catch (e) {
            $.writeln("Render queue error: " + e);
        }
    }

    app.endUndoGroup();
    
    // Auto-render if flag is set
    if (AUTO_RENDER === "true") {
        if (app.project.renderQueue.numItems > 0) {
            $.writeln("AUTO_RENDER: Starting render...");
            app.project.renderQueue.render();
            $.writeln("AUTO_RENDER: Render complete.");
        } else {
            $.writeln("AUTO_RENDER: No items in render queue.");
            writeErrorLog("No items in render queue");
        }
        app.quit();
    } else {
        alert("ONYX batch processing complete!\n\nReview in Render Queue, then click Render.");
    }
}

// Write error log for batch processing
function writeErrorLog(message) {
    if (JOBS_PATH.indexOf("{{") === -1 && JOBS_PATH !== "") {
        var errorFile = new File(JOBS_PATH + "/batch_error.txt");
        errorFile.open("w");
        errorFile.write(message);
        errorFile.close();
    }
}


// -----------------------------
// ONYX-SPECIFIC FUNCTIONS
// -----------------------------

function addOnyxMarkersToAudio(lyricComp, markers) {
    // Add markers to AUDIO layer for timing triggers
    var audio = ensureAudioLayer(lyricComp);
    if (!audio) { 
        $.writeln("No AUDIO layer found in " + lyricComp.name); 
        return; 
    }

    var mk = audio.property("Marker");
    if (!mk) { 
        $.writeln("No Marker prop on AUDIO in " + lyricComp.name); 
        return; 
    }

    // Clear existing markers
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);

    var lastT = 0;
    for (var k = 0; k < markers.length; k++) {
        var m = markers[k];
        var t = Number(m.time) || 0;
        var markerComment = m.text || ("Segment " + (k + 1));
        
        try {
            mk.setValueAtTime(t, new MarkerValue(markerComment));
            if (t > lastT) lastT = t;
        } catch (e) {
            $.writeln("Marker set failed at " + t + "s: " + e.toString());
        }
    }
    
    if (lastT + 2 > lyricComp.duration) {
        lyricComp.duration = lastT + 2;
    }
    
    $.writeln("Added " + markers.length + " markers to AUDIO in " + lyricComp.name);
}


function injectOnyxSegmentsToLyricText(lyricComp, markers) {
    // Find LYRIC_TEXT layer
    var lyricText = lyricComp.layer("LYRIC_TEXT");
    if (!lyricText) {
        $.writeln("LYRIC_TEXT layer not found in " + lyricComp.name);
        return;
    }

    var sourceText = lyricText.property("Source Text");
    if (!sourceText) {
        $.writeln("No Source Text property on LYRIC_TEXT");
        return;
    }

    // Build the segments array string
    var segmentsArray = buildSegmentsArrayStringWithEnds(markers);
    
    // Build the LYRIC_TEXT expression (word-by-word reveal, 3 words per line for Onyx)
    var onyxExpression = [
        '// ONYX: Word-by-word reveal (3 words per line)',
        segmentsArray,
        '',
        'var ctrl = thisComp.layer("LYRIC CONTROL");',
        'var segIndex = ctrl.effect("Lyric Data")("Point")[0];',
        'var wordsPerLine = 3;  // Onyx uses 3 words per line',
        '',
        'if (segIndex < 1 || segIndex > segments.length) {',
        '    "";',
        '} else {',
        '    var seg = segments[segIndex - 1];',
        '    var output = "";',
        '    var wordCount = 0;',
        '',
        '    for (var i = 0; i < seg.words.length; i++) {',
        '        if (time >= seg.words[i].s) {',
        '            var word = seg.words[i].w;',
        '            if (wordCount > 0) {',
        '                if (wordCount % wordsPerLine === 0) {',
        '                    output += "\\r";',
        '                } else {',
        '                    output += " ";',
        '                }',
        '            }',
        '            output += word;',
        '            wordCount++;',
        '        }',
        '    }',
        '    output;',
        '}'
    ].join('\n');

    // Apply the expression
    sourceText.expression = onyxExpression;
    
    // Add Gaussian Blur for word reveal effect
    addGaussianBlurToLyricText(lyricText, markers);
    
    $.writeln("Injected Onyx word-reveal expression with " + markers.length + " segments");
}


function buildSegmentsArrayStringWithEnds(markers) {
    // Build: var segments = [{t:0.18, e:2.5, words:[{w:"It",s:0.18},{w:"ain't",s:0.64}]}, ...];
    var segmentStrings = [];
    
    for (var i = 0; i < markers.length; i++) {
        var m = markers[i];
        var t = Number(m.time) || 0;
        var e = Number(m.end_time) || (t + 5);
        var words = m.words || [];
        
        // Build words array string
        var wordStrings = [];
        for (var j = 0; j < words.length; j++) {
            var word = words[j];
            var w = String(word.word || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
            var s = Number(word.start) || 0;
            wordStrings.push('{w:"' + w + '",s:' + s.toFixed(3) + '}');
        }
        
        var segStr = '{t:' + t.toFixed(3) + ',e:' + e.toFixed(3) + ',words:[' + wordStrings.join(',') + ']}';
        segmentStrings.push(segStr);
    }
    
    return 'var segments = [\n    ' + segmentStrings.join(',\n    ') + '\n];';
}


function addGaussianBlurToLyricText(lyricText, markers) {
    // Add Gaussian Blur effect to LYRIC_TEXT layer
    var effects = lyricText.property("Effects");
    
    // Check if Gaussian Blur already exists
    var gaussBlur = null;
    for (var i = 1; i <= effects.numProperties; i++) {
        var eff = effects.property(i);
        if (eff.matchName === "ADBE Gaussian Blur 2") {
            gaussBlur = eff;
            break;
        }
    }
    
    // Add if doesn't exist
    if (!gaussBlur) {
        try {
            gaussBlur = effects.addProperty("ADBE Gaussian Blur 2");
        } catch (e) {
            $.writeln("Could not add Gaussian Blur effect: " + e.toString());
            return;
        }
    }
    
    // Build segments array for blur expression
    var segmentsArray = buildSegmentsArrayStringWithEnds(markers);
    
    // Expression: blur spikes when word appears, quickly sharpens
    var blurExpression = [
        '// Gaussian blur on word reveal',
        segmentsArray,
        '',
        'var ctrl = thisComp.layer("LYRIC CONTROL");',
        'var segIndex = ctrl.effect("Lyric Data")("Point")[0];',
        'var wordBlurMax = 15;',
        'var wordFadeTime = 0.12;',
        '',
        'if (segIndex < 1 || segIndex > segments.length) {',
        '    0;',
        '} else {',
        '    var seg = segments[segIndex - 1];',
        '    var blur = 0;',
        '',
        '    // Word reveal blur (sharpens as word appears)',
        '    for (var i = 0; i < seg.words.length; i++) {',
        '        var wordStart = seg.words[i].s;',
        '        var timeSinceWord = time - wordStart;',
        '        if (timeSinceWord >= 0 && timeSinceWord < wordFadeTime) {',
        '            var wordBlur = wordBlurMax * (1 - timeSinceWord / wordFadeTime);',
        '            if (wordBlur > blur) blur = wordBlur;',
        '        }',
        '    }',
        '    blur;',
        '}'
    ].join('\n');
    
    try {
        gaussBlur.property("Blurriness").expression = blurExpression;
        $.writeln("Added Gaussian Blur expression to LYRIC_TEXT");
    } catch (e) {
        $.writeln("Could not set blur expression: " + e.toString());
    }
}


function setAllCompDurations(jobId, audioPath) {
    // Import audio to get accurate duration
    var audioFile = new File(audioPath);
    if (!audioFile.exists) {
        $.writeln("Audio file not found for duration check: " + audioPath);
        return;
    }
    
    var imported = app.project.importFile(new ImportOptions(audioFile));
    var dur = imported.duration;
    imported.remove();
    
    $.writeln("Audio duration for job " + jobId + ": " + dur + "s");

    // Set OUTPUT comp duration
    try {
        var outputComp = findCompByName("OUTPUT " + jobId);
        outputComp.duration = dur;
        outputComp.workAreaStart = 0;
        outputComp.workAreaDuration = dur;
        $.writeln("Set OUTPUT " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set OUTPUT " + jobId + " duration: " + e.toString());
    }
    
    // Set PRE-OUTPUT comp duration
    try {
        var preOutputComp = findCompByName("PRE-OUTPUT " + jobId);
        preOutputComp.duration = dur;
        preOutputComp.workAreaStart = 0;
        preOutputComp.workAreaDuration = dur;
        $.writeln("Set PRE-OUTPUT " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set PRE-OUTPUT " + jobId + " duration: " + e.toString());
    }
    
    // Set LYRIC FONT comp duration
    try {
        var lyricComp = findCompByName("LYRIC FONT " + jobId);
        lyricComp.duration = dur;
        lyricComp.workAreaStart = 0;
        lyricComp.workAreaDuration = dur;
        $.writeln("Set LYRIC FONT " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set LYRIC FONT " + jobId + " duration: " + e.toString());
    }
    
    // Set BACKGROUND comp duration
    try {
        var bgComp = findCompByName("BACKGROUND " + jobId);
        bgComp.duration = dur;
        bgComp.workAreaStart = 0;
        bgComp.workAreaDuration = dur;
        $.writeln("Set BACKGROUND " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set BACKGROUND " + jobId + " duration: " + e.toString());
    }
    
    // Set Assets comp duration
    try {
        var assetsComp = findCompByName("Assets " + jobId);
        assetsComp.duration = dur;
        assetsComp.workAreaStart = 0;
        assetsComp.workAreaDuration = dur;
        $.writeln("Set Assets " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set Assets " + jobId + " duration: " + e.toString());
    }
}


function relinkFootageInsideOutputFolder(jobId, audioPath, coverPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln("OUTPUT" + jobId + " folder not found.");
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
        $.writeln("Assets folder not found inside OUTPUT" + jobId);
        return;
    }

    var audioFile = new File(audioPath);
    var coverFile = new File(coverPath);

    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (!(it instanceof FootageItem)) continue;

        var name = (it.name || "").toUpperCase();
        
        // Match audio files
        var isAudio = (name === "AUDIO") || 
                      (name.indexOf("AUDIO") === 0) || 
                      (name.indexOf(".WAV") !== -1);
        
        // Match cover files
        var isCover = (name === "COVER") ||
                      (name === "COVER.PNG") ||
                      (name === "COVER.JPG") ||
                      (name.indexOf("COVER") === 0);
        
        try {
            if (isAudio && audioFile.exists) {
                it.replace(audioFile);
                $.writeln("Replaced " + it.name + " inside Assets OT" + jobId);
            } else if (isCover && coverFile.exists) {
                it.replace(coverFile);
                $.writeln("Replaced " + it.name + " inside Assets OT" + jobId);
            }
        } catch (e) {
            $.writeln("Could not relink " + it.name + ": " + e.toString());
        }
    }
}


function applyBackgroundColors(jobId, colors) {
    if (!colors || colors.length < 2) {
        $.writeln("Not enough colors for job " + jobId);
        return;
    }

    var bgComp;
    try {
        bgComp = findCompByName("BACKGROUND " + jobId);
    } catch (_) {
        $.writeln("BACKGROUND " + jobId + " not found");
        return;
    }

    // Find the Gradient layer
    var gradientLayer = bgComp.layer("Gradient");
    if (!gradientLayer) {
        $.writeln("Gradient layer not found in BACKGROUND " + jobId);
        return;
    }

    // Find the 4-Color Gradient effect
    var effectParade = gradientLayer.property("ADBE Effect Parade");
    if (!effectParade) {
        $.writeln("No effects on Gradient layer in BACKGROUND " + jobId);
        return;
    }

    var gradient4Color = effectParade.property("4-Color Gradient");
    if (!gradient4Color) {
        $.writeln("4-Color Gradient effect not found on Gradient layer in BACKGROUND " + jobId);
        return;
    }

    try {
        var color1Prop = gradient4Color.property("Color 1");
        var color2Prop = gradient4Color.property("Color 2");
        var color3Prop = gradient4Color.property("Color 3");
        var color4Prop = gradient4Color.property("Color 4");

        if (color1Prop) color1Prop.setValue(hexToRGB(colors[0]));
        if (color2Prop) color2Prop.setValue(hexToRGB(colors[1]));
        if (color3Prop) color3Prop.setValue(hexToRGB(colors.length > 2 ? colors[2] : colors[0]));
        if (color4Prop) color4Prop.setValue(hexToRGB(colors[0]));

        $.writeln("4-Color Gradient updated for job " + jobId);
    } catch (e) {
        $.writeln("Failed to apply gradient colors for job " + jobId + ": " + e.toString());
    }
}


function updateSongTitle(jobId, titleText) {
    if (!titleText) return;
    try {
        var assetsComp = findCompByName("Assets " + jobId);
        if (!assetsComp) { $.writeln("Assets " + jobId + " not found."); return; }

        var targetTextLayer = null;
        for (var i = 1; i <= assetsComp.numLayers; i++) {
            var lyr = assetsComp.layer(i);
            var txtProp = lyr.property("Source Text");
            if (txtProp) { targetTextLayer = lyr; break; }
        }

        if (!targetTextLayer) {
            $.writeln("No text layer found in " + assetsComp.name);
            return;
        }

        var txtProp = targetTextLayer.property("Source Text");
        var doc = txtProp.value;
        doc.text = String(titleText);
        txtProp.setValue(doc);

        $.writeln("Set song title for job " + jobId + ": " + titleText);
    } catch (e) {
        $.writeln("Could not update title for job " + jobId + ": " + e.toString());
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
        $.writeln("Footage '" + footageName + "' not found.");
        return;
    }

    for (var L = 1; L <= assetComp.numLayers; L++) {
        var lyr = assetComp.layer(L);
        if (!(lyr instanceof AVLayer)) continue;
        if (!(lyr.source instanceof FootageItem)) continue;

        var srcName = (lyr.source.name || "").toLowerCase();
        var lyrName = (lyr.name || "").toLowerCase();

        var isCoverLayer =
            lyrName === "cover" ||
            lyrName === "cover.png" ||
            lyrName.indexOf("album") !== -1 ||
            lyrName.indexOf("art") !== -1 ||
            srcName === "cover" ||
            srcName === "cover.png" ||
            srcName.indexOf("album") !== -1;

        if (!isCoverLayer) continue;

        try {
            lyr.replaceSource(coverFootage, false);
            $.writeln("Replaced album art layer in " + assetComp.name);
        } catch (e) {
            $.writeln("Could not replace layer: " + e.toString());
        }
    }
}


function addToRenderQueue(comp, jobFolder, jobId, songTitle, suffix) {
    try {
        jobFolder = String(jobFolder).replace(/\\/g, "/");
        
        var jobFolderObj = new Folder(jobFolder);
        var root = jobFolderObj.parent;
        
        var renderDir = new Folder(root.fsName + "/renders");
        if (!renderDir.exists) {
            renderDir.create();
        }

        var safeTitle = sanitizeFilename(songTitle);
        var filename = safeTitle + (suffix || "") + ".mp4";
        var outPath = renderDir.fsName.replace(/\\/g, "/") + "/" + filename;
        var outFile = new File(outPath);

        var rq = app.project.renderQueue.items.add(comp);
        rq.outputModule(1).file = outFile;

        return outPath;
    } catch (err) {
        $.writeln("addToRenderQueue error: " + err.toString());
        return null;
    }
}


// -----------------------------
// SHARED HELPER FUNCTIONS
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
    if (f.exists) {
        return f.fsName.replace(/\\/g, "/");
    }

    var base = File($.fileName).parent.parent.parent;
    f = new File(base.fsName + "/" + p);

    return f.fsName.replace(/\\/g, "/");
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

function ensureAudioLayer(comp) {
    var lyr = comp.layer("AUDIO");
    if (lyr) return lyr;

    for (var i = 1; i <= comp.numLayers; i++) {
        var L = comp.layer(i);
        if (L instanceof AVLayer && L.hasAudio) {
            try { L.name = "AUDIO"; } catch (_) {}
            return L;
        }
    }
    return null;
}

function sanitizeFilename(name) {
    if (!name) return "untitled";
    return String(name)
        .replace(/[\/\\:*?"<>|]/g, "")
        .replace(/\s+/g, " ")
        .replace(/^\s+|\s+$/g, "");
}

function clearAllJobComps() {
    $.writeln("Clearing all ONYX_JOB comps...");
    var count = 0;
    
    for (var i = app.project.numItems; i >= 1; i--) {
        var it = app.project.item(i);
        
        if (it instanceof CompItem && it.name.indexOf("ONYX_JOB_") === 0) {
            try {
                it.remove();
                count++;
            } catch (e) {}
        }
    }
    
    $.writeln("Deleted " + count + " old ONYX job comps");
}

// -----------------------------
// RUN
// -----------------------------
main();