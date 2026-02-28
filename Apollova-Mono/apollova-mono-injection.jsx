// -------------------------------------------------------
// Apollova Mono - After Effects Automation
// Modified Aurora template with word-by-word reveal
// -------------------------------------------------------
// Usage:
//  1) Run main_mono.py to build /jobs/job_001 → job_012
//  2) Open AE project (same Aurora template)
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
// MAIN
// -----------------------------
function main() {
    app.beginUndoGroup("mono Batch Music Video Build");

    clearAllJobComps();

    // Clear render queue before adding new jobs
    for (var i = app.project.renderQueue.numItems; i >= 1; i--) {
        try { app.project.renderQueue.item(i).remove(); } catch (e) {}
    }
    $.writeln("Render queue cleared.");

    var jobsFolder = Folder.selectDialog("Select your /jobs folder (Visuals-Mono/jobs)");
    if (!jobsFolder) return;

    var subfolders = jobsFolder.getFiles(function (f) { return f instanceof Folder; });
    var jsonFiles = [];
    
    for (var i = 0; i < subfolders.length; i++) {
        // Look for mono_data.json in each job folder
        var files = subfolders[i].getFiles("mono_data.json");
        if (files && files.length > 0) {
            jsonFiles.push(files[0]);
        }
    }
    
    if (jsonFiles.length === 0) {
        alert("No mono_data.json files found inside subfolders of " + jobsFolder.fsName);
        return;
    }

    for (var j = 0; j < jsonFiles.length; j++) {
        var monoFile = jsonFiles[j];
        if (!monoFile.exists || !monoFile.open("r")) continue;
        var monoText = monoFile.read();
        monoFile.close();
        if (!monoText) continue;

        var monoData;
        try { monoData = JSON.parse(monoText); }
        catch (e) { alert("Error parsing " + monoFile.name + ": " + e.toString()); continue; }

        // Also read job_data.json for paths and metadata
        var jobFolder = monoFile.parent;
        var jobDataFile = new File(jobFolder.fsName + "/job_data.json");
        var jobData = {};
        
        if (jobDataFile.exists && jobDataFile.open("r")) {
            var jobDataText = jobDataFile.read();
            jobDataFile.close();
            try { jobData = JSON.parse(jobDataText); }
            catch (e) { $.writeln("Could not parse job_data.json"); }
        }

        // Convert paths to absolute
        jobData.audio_trimmed = toAbsolute(jobData.audio_trimmed || (jobFolder.fsName + "/audio_trimmed.wav"));
        jobData.job_folder = jobFolder.fsName.replace(/\\/g, "/");
        
        // For mono, we may or may not have cover image (optional)
        var hasCoverImage = false;
        if (jobData.cover_image) {
            jobData.cover_image = toAbsolute(jobData.cover_image);
            var imageFile = new File(jobData.cover_image);
            hasCoverImage = imageFile.exists;
        }

        var jobId = jobData.job_id || (j + 1);
        var songTitle = jobData.song_title || "Unknown";
        var markers = monoData.markers || [];

        $.writeln("──────── MONO Job " + jobId + " ────────");
        $.writeln("Song: " + songTitle);
        $.writeln("Markers: " + markers.length);

        var audioFile = new File(jobData.audio_trimmed);
        if (!audioFile.exists) { 
            alert("Missing audio:\n" + jobData.audio_trimmed); 
            continue; 
        }

        // Duplicate MAIN template
        var template = findCompByName("MAIN");
        var newComp = template.duplicate();
        newComp.name = "MONO_JOB_" + ("00" + jobId).slice(-3);

        // Move duplicated comp into correct OUTPUT folder
        moveItemToFolder(newComp, "OUTPUT" + jobId);

        // Relink audio (and cover if exists)
        if (hasCoverImage) {
            relinkFootageInsideOutputFolder(jobId, jobData.audio_trimmed, jobData.cover_image);
            autoResizeCoverInOutput(jobId);
        } else {
            relinkAudioOnly(jobId, jobData.audio_trimmed);
        }
        
        setWorkAreaToAudioDuration(jobId);
        setOutputWorkAreaToAudio(jobId, jobData.audio_trimmed);
        updateSongTitle(jobId, songTitle);

        // Lyrics - MONO STYLE (word-by-word)
        var lyricComp;
        try { lyricComp = findCompByName("LYRIC FONT " + jobId); }
        catch (e) { $.writeln("Missing LYRIC FONT " + jobId + " – skipping lyrics."); continue; }

        // Add markers to AUDIO layer in LYRIC FONT comp
        addMonoMarkersToAudio(lyricComp, markers);
        
        // Inject word-by-word segments into LYRIC_TEXT expression
        injectMonoSegmentsToLyricText(lyricComp, markers);

        // Add markers to BACKGROUND comp for color flip
        try {
            var bgComp = findCompByName("BACKGROUND " + jobId);
            addMonoMarkersToBackground(bgComp, markers);
            $.writeln("Added markers to BACKGROUND " + jobId);
        } catch (e) {
            $.writeln("BACKGROUND " + jobId + " not found – skipping color flip markers.");
        }

        // Album art (optional for Mono)
        if (hasCoverImage) {
            try {
                var assetsComp = findCompByName("Assets " + jobId);
                retargetImageLayersToFootage(assetsComp, "COVER");
                $.writeln("Album art retargeted for job " + jobId);
            } catch (e) {
                $.writeln("Assets " + jobId + " not found – skipping album art.");
            }
        }

        // Add to render queue
        try {
            var outputComp = null;
            // Try different naming conventions
            try { outputComp = findCompByName("OUTPUT " + jobId); } catch(e1) {}
            if (!outputComp) {
                try { outputComp = findCompByName("OUTPUT" + jobId); } catch(e2) {}
            }
            if (!outputComp) {
                try { outputComp = findCompByName("OUTPUT " + jobId + " "); } catch(e3) {}
            }
            
            if (outputComp) {
                var renderPath = addToRenderQueue(
                    outputComp,
                    jobData.job_folder,
                    jobId,
                    songTitle
                );
                $.writeln("Queued: " + renderPath);
            } else {
                $.writeln("Could not find OUTPUT comp for job " + jobId + " - skipping render queue");
            }
        } catch (e) {
            $.writeln("Render queue error: " + e);
        }
    }

    alert("MONO batch processing complete!\n\nReview in Render Queue, then click Render.");
    app.endUndoGroup();
}


// -----------------------------
// Mono-SPECIFIC FUNCTIONS
// -----------------------------

function addMonoMarkersToAudio(lyricComp, markers) {
    // Add simple markers to AUDIO layer (just for timing triggers)
    // LYRIC CONTROL reads these to determine current segment index
    
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
        
        // Simple marker - just the segment text as comment (like Aurora)
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


function addMonoMarkersToBackground(bgComp, markers) {
    // Add markers to the audio layer in BACKGROUND comp for color flip
    // Find the audio layer (might be named "audio_trimmed.wav" or "AUDIO")
    
    var audioLayer = null;
    
    // Try common audio layer names
    var audioNames = ["audio_trimmed.wav", "AUDIO", "audio"];
    for (var n = 0; n < audioNames.length; n++) {
        try {
            audioLayer = bgComp.layer(audioNames[n]);
            if (audioLayer) break;
        } catch (e) {}
    }
    
    // Fallback: find first layer with audio
    if (!audioLayer) {
        for (var i = 1; i <= bgComp.numLayers; i++) {
            var L = bgComp.layer(i);
            if (L instanceof AVLayer && L.hasAudio) {
                audioLayer = L;
                break;
            }
        }
    }
    
    if (!audioLayer) {
        $.writeln("No audio layer found in " + bgComp.name);
        return;
    }

    var mk = audioLayer.property("Marker");
    if (!mk) {
        $.writeln("No Marker property on audio layer in " + bgComp.name);
        return;
    }

    // Clear existing markers
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);

    // Add markers at each segment time
    for (var k = 0; k < markers.length; k++) {
        var m = markers[k];
        var t = Number(m.time) || 0;
        var markerComment = m.text || ("Segment " + (k + 1));
        
        try {
            mk.setValueAtTime(t, new MarkerValue(markerComment));
        } catch (e) {
            $.writeln("Background marker set failed at " + t + "s: " + e.toString());
        }
    }
    
    $.writeln("Added " + markers.length + " markers to audio in " + bgComp.name);
}


function injectMonoSegmentsToLyricText(lyricComp, markers) {
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
    
    // Build the LYRIC_TEXT expression (word-by-word reveal, 4 words per line)
    var monoExpression = [
        '// Mono: Word-by-word reveal',
        segmentsArray,
        '',
        'var ctrl = thisComp.layer("LYRIC CONTROL");',
        'var segIndex = ctrl.effect("Lyric Data")("Point")[0];',
        'var wordsPerLine = 4;',
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
    sourceText.expression = monoExpression;
    
    // Add Gaussian Blur for word reveal effect
    addGaussianBlurToLyricText(lyricText, markers);
    
    $.writeln("Injected Mono word-reveal expression with " + markers.length + " segments");
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


function addLyricTextOpacity(lyricText, markers) {
    // Add opacity expression for crossfade
    var opacity = lyricText.property("Transform").property("Opacity");
    
    var segmentsArray = buildSegmentsArrayStringWithEnds(markers);
    
    var opacityExpression = [
        '// Opacity - fade out at end, stay hidden until next segment starts',
        segmentsArray,
        '',
        'var ctrl = thisComp.layer("LYRIC CONTROL");',
        'var segIndex = ctrl.effect("Lyric Data")("Point")[0];',
        'var fadeDur = 0.15;  // Fast fade out',
        '',
        'if (segIndex < 1 || segIndex > segments.length) {',
        '    0;',
        '} else {',
        '    var seg = segments[segIndex - 1];',
        '    var lastWordTime = seg.words[seg.words.length - 1].s + 0.3;',
        '',
        '    // Check if we should be fading out (gap before next segment)',
        '    if (segIndex < segments.length) {',
        '        var nextSegStart = segments[segIndex].t;',
        '',
        '        // After last word, fade out',
        '        if (time > lastWordTime && time < lastWordTime + fadeDur) {',
        '            var progress = (time - lastWordTime) / fadeDur;',
        '            linear(progress, 0, 1, 100, 0);',
        '        }',
        '        // Stay hidden until next segment starts',
        '        else if (time >= lastWordTime + fadeDur && time < nextSegStart) {',
        '            0;',
        '        }',
        '        // Next segment started - full opacity (words appear via text expression)',
        '        else {',
        '            100;',
        '        }',
        '    } else {',
        '        // Last segment - just show normally, fade out at end',
        '        if (time > lastWordTime && time < lastWordTime + fadeDur) {',
        '            var progress = (time - lastWordTime) / fadeDur;',
        '            linear(progress, 0, 1, 100, 0);',
        '        } else if (time >= lastWordTime + fadeDur) {',
        '            0;',
        '        } else {',
        '            100;',
        '        }',
        '    }',
        '}'
    ].join('\n');
    
    try {
        opacity.expression = opacityExpression;
        $.writeln("Added opacity expression to LYRIC_TEXT");
    } catch (e) {
        $.writeln("Could not set opacity expression: " + e.toString());
    }
}


function setupTagLayer(lyricComp, markers) {
    // Find or create TAG_TEXT layer
    var tagLayer = null;
    try {
        tagLayer = lyricComp.layer("TAG_TEXT");
    } catch (e) {}
    
    if (!tagLayer) {
        // Create TAG_TEXT layer
        try {
            tagLayer = lyricComp.layers.addText("@apollova-mono");
            tagLayer.name = "TAG_TEXT";
            
            // Position it in center (same as LYRIC_TEXT)
            var lyricText = lyricComp.layer("LYRIC_TEXT");
            if (lyricText) {
                var lyricPos = lyricText.property("Transform").property("Position").value;
                tagLayer.property("Transform").property("Position").setValue(lyricPos);
            } else {
                tagLayer.property("Transform").property("Position").setValue([lyricComp.width/2, lyricComp.height/2]);
            }
            
            $.writeln("Created TAG_TEXT layer in " + lyricComp.name);
        } catch (e) {
            $.writeln("Could not create TAG_TEXT layer: " + e.toString());
            return;
        }
    }
    
    // Add Gaussian Blur to tag layer
    var effects = tagLayer.property("Effects");
    var gaussBlur = null;
    for (var i = 1; i <= effects.numProperties; i++) {
        var eff = effects.property(i);
        if (eff.matchName === "ADBE Gaussian Blur 2") {
            gaussBlur = eff;
            break;
        }
    }
    if (!gaussBlur) {
        try {
            gaussBlur = effects.addProperty("ADBE Gaussian Blur 2");
        } catch (e) {
            $.writeln("Could not add Gaussian Blur to TAG_TEXT: " + e.toString());
        }
    }
    
    var segmentsArray = buildSegmentsArrayStringWithEnds(markers);
    
    // Tag opacity expression (visible only between segments)
    var tagOpacityExpression = [
        '// Tag appears between segments - quick flash',
        segmentsArray,
        '',
        'var ctrl = thisComp.layer("LYRIC CONTROL");',
        'var segIndex = ctrl.effect("Lyric Data")("Point")[0];',
        'var fadeDur = 0.1;  // Fast fade',
        '',
        'if (segIndex < 1 || segIndex >= segments.length) {',
        '    0;',
        '} else {',
        '    var seg = segments[segIndex - 1];',
        '    var lastWordTime = seg.words[seg.words.length - 1].s + 0.3;',
        '    var nextSegStart = segments[segIndex].t;',
        '    var gapDuration = nextSegStart - lastWordTime;',
        '    var tagStart = lastWordTime + fadeDur;  // Tag appears after lyrics fade',
        '    var tagEnd = nextSegStart - 0.2;  // Tag disappears before next segment',
        '',
        '    // Only show if there is enough gap',
        '    if (gapDuration < 0.5) {',
        '        0;',
        '    }',
        '    // Fade in',
        '    else if (time >= tagStart && time < tagStart + fadeDur) {',
        '        var progress = (time - tagStart) / fadeDur;',
        '        linear(progress, 0, 1, 0, 100);',
        '    }',
        '    // Visible',
        '    else if (time >= tagStart + fadeDur && time < tagEnd - fadeDur) {',
        '        100;',
        '    }',
        '    // Fade out',
        '    else if (time >= tagEnd - fadeDur && time < tagEnd) {',
        '        var progress = (time - (tagEnd - fadeDur)) / fadeDur;',
        '        linear(progress, 0, 1, 100, 0);',
        '    }',
        '    else {',
        '        0;',
        '    }',
        '}'
    ].join('\n');
    
    // Tag blur expression (blur in and out)
    var tagBlurExpression = [
        '// Tag blur for smooth appearance',
        segmentsArray,
        '',
        'var ctrl = thisComp.layer("LYRIC CONTROL");',
        'var segIndex = ctrl.effect("Lyric Data")("Point")[0];',
        'var maxBlur = 15;',
        'var fadeDur = 0.1;',
        '',
        'if (segIndex < 1 || segIndex >= segments.length) {',
        '    maxBlur;',
        '} else {',
        '    var seg = segments[segIndex - 1];',
        '    var lastWordTime = seg.words[seg.words.length - 1].s + 0.3;',
        '    var nextSegStart = segments[segIndex].t;',
        '    var gapDuration = nextSegStart - lastWordTime;',
        '    var tagStart = lastWordTime + fadeDur;',
        '    var tagEnd = nextSegStart - 0.2;',
        '',
        '    if (gapDuration < 0.5) {',
        '        maxBlur;',
        '    }',
        '    // Sharpen as fades in',
        '    else if (time >= tagStart && time < tagStart + fadeDur) {',
        '        var progress = (time - tagStart) / fadeDur;',
        '        linear(progress, 0, 1, maxBlur, 0);',
        '    }',
        '    // Sharp while visible',
        '    else if (time >= tagStart + fadeDur && time < tagEnd - fadeDur) {',
        '        0;',
        '    }',
        '    // Blur as fades out',
        '    else if (time >= tagEnd - fadeDur && time < tagEnd) {',
        '        var progress = (time - (tagEnd - fadeDur)) / fadeDur;',
        '        linear(progress, 0, 1, 0, maxBlur);',
        '    }',
        '    else {',
        '        maxBlur;',
        '    }',
        '}'
    ].join('\n');
    
    try {
        tagLayer.property("Transform").property("Opacity").expression = tagOpacityExpression;
        $.writeln("Added opacity expression to TAG_TEXT");
    } catch (e) {
        $.writeln("Could not set TAG opacity expression: " + e.toString());
    }
    
    if (gaussBlur) {
        try {
            gaussBlur.property("Blurriness").expression = tagBlurExpression;
            $.writeln("Added blur expression to TAG_TEXT");
        } catch (e) {
            $.writeln("Could not set TAG blur expression: " + e.toString());
        }
    }
}


function buildSegmentsArrayString(markers) {
    // Build: var segments = [{t:0.18, words:[{w:"It",s:0.18},{w:"ain't",s:0.64}]}, ...];
    
    var segmentStrings = [];
    
    for (var i = 0; i < markers.length; i++) {
        var m = markers[i];
        var t = Number(m.time) || 0;
        var words = m.words || [];
        
        // Build words array string
        var wordStrings = [];
        for (var j = 0; j < words.length; j++) {
            var word = words[j];
            var w = String(word.word || "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
            var s = Number(word.start) || 0;
            wordStrings.push('{w:"' + w + '",s:' + s.toFixed(3) + '}');
        }
        
        var segStr = '{t:' + t.toFixed(3) + ',words:[' + wordStrings.join(',') + ']}';
        segmentStrings.push(segStr);
    }
    
    return 'var segments = [\n    ' + segmentStrings.join(',\n    ') + '\n];';
}


function relinkAudioOnly(jobId, audioPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln("OUTPUT" + jobId + " folder not found.");
        return;
    }

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
    if (!audioFile.exists) {
        $.writeln("Missing audio file for job " + jobId);
        return;
    }

    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (!(it instanceof FootageItem)) continue;

        var name = (it.name || "").toUpperCase();
        // Match AUDIO, audio_trimmed.wav, or any .wav file
        var isAudio = (name === "AUDIO") || 
                      (name.indexOf("AUDIO") === 0) || 
                      (name.indexOf(".WAV") !== -1);
        
        if (isAudio) {
            try {
                it.replace(audioFile);
                $.writeln("Replaced " + it.name + " inside Assets OT" + jobId);
            } catch (e) {
                $.writeln("Could not relink audio: " + e.toString());
            }
        }
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

function relinkFootageInsideOutputFolder(jobId, audioPath, coverPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln("OUTPUT" + jobId + " folder not found.");
        return;
    }

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
        
        try {
            if (isAudio && audioFile.exists) {
                it.replace(audioFile);
                $.writeln("Replaced " + it.name + " inside Assets OT" + jobId);
            } else if (name === "COVER" && coverFile.exists) {
                it.replace(coverFile);
                $.writeln("Replaced COVER inside Assets OT" + jobId);
            }
        } catch (e) {
            $.writeln("Could not relink " + it.name + ": " + e.toString());
        }
    }
}

function autoResizeCoverInOutput(jobId) {
    var comp;
    try { comp = findCompByName("OUTPUT " + jobId); }
    catch(_) { return; }

    var cw = comp.width;
    var ch = comp.height;

    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (!(lyr instanceof AVLayer)) continue;

        var isCover = (lyr.name.toUpperCase() === "COVER") ||
                      (lyr.source && lyr.source.name.toUpperCase() === "COVER");
        if (!isCover) continue;

        var lw = lyr.source.width;
        var lh = lyr.source.height;
        if (!lw || !lh) continue;

        var scaleW = cw / lw;
        var scaleH = ch / lh;
        var scale = 100 * Math.max(scaleW, scaleH);

        try {
            lyr.property("Scale").setValue([scale, scale]);
            lyr.property("Position").setValue([cw / 2, ch / 2]);
        } catch(e) {}

        $.writeln("Auto-Fill scaled COVER in " + comp.name);
        return;
    }
}

function setWorkAreaToAudioDuration(jobId) {
    var comp;
    try { comp = findCompByName("LYRIC FONT " + jobId); }
    catch(_) { return; }

    var audio = ensureAudioLayer(comp);
    if (!audio || !audio.source || !audio.source.duration) {
        $.writeln("Could not get audio duration for LYRIC FONT " + jobId);
        return;
    }

    var dur = audio.source.duration;
    comp.duration = dur;
    comp.workAreaStart = 0;
    comp.workAreaDuration = dur;
    $.writeln("Set LYRIC FONT " + jobId + " duration to " + dur + "s");
}

function setOutputWorkAreaToAudio(jobId, audioPath) {
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
}

function updateSongTitle(jobId, titleText) {
    if (!titleText) return;
    try {
        var assetsComp = findCompByName("Assets " + jobId);
        if (!assetsComp) return;

        var targetTextLayer = null;
        for (var i = 1; i <= assetsComp.numLayers; i++) {
            var lyr = assetsComp.layer(i);
            var txtProp = lyr.property("Source Text");
            if (txtProp) { targetTextLayer = lyr; break; }
        }

        if (!targetTextLayer) return;

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

    if (!coverFootage) return;

    for (var L = 1; L <= assetComp.numLayers; L++) {
        var lyr = assetComp.layer(L);
        if (!(lyr instanceof AVLayer)) continue;
        if (!(lyr.source instanceof FootageItem)) continue;

        var srcName = (lyr.source.name || "").toLowerCase();
        var lyrName = (lyr.name || "").toLowerCase();

        var isCoverLayer =
            lyrName === "cover" ||
            lyrName.indexOf("album") !== -1 ||
            lyrName.indexOf("art") !== -1 ||
            srcName === "cover" ||
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
        // Normalize path
        jobFolder = String(jobFolder).replace(/\\/g, "/");
        
        // Get parent folder (jobs folder) and create renders directory
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

        // Add to render queue
        var rq = app.project.renderQueue.items.add(comp);
        
        // Set output file (skip templates - use defaults)
        rq.outputModule(1).file = outFile;

        return outPath;
    } catch (err) {
        $.writeln("addToRenderQueue error: " + err.toString());
        return null;
    }
}

function sanitizeFilename(name) {
    if (!name) return "untitled";
    return String(name)
        .replace(/[\/\\:*?"<>|]/g, "")
        .replace(/\s+/g, " ")
        .replace(/^\s+|\s+$/g, "");
}

function clearAllJobComps() {
    $.writeln("Clearing all MONO_JOB comps...");
    var count = 0;
    
    for (var i = app.project.numItems; i >= 1; i--) {
        var it = app.project.item(i);
        
        if (it instanceof CompItem && it.name.indexOf("MONO_JOB_") === 0) {
            try {
                it.remove();
                count++;
            } catch (e) {}
        }
    }
    
    $.writeln("Deleted " + count + " old MONO job comps");
}

// -----------------------------
// RUN
// -----------------------------
main();