import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  Pressable,
  ScrollView,
  StyleSheet,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Colors } from '../../constants/colors';
import {
  generateJobs,
  getSmartPickerPreview,
  reshuffleSmartPicker,
  Song,
} from '../../api/endpoints';

type Template = 'Aurora' | 'Mono' | 'Onyx';
type Mode = 'smart_picker' | 'manual';
type JobCount = 6 | 12;

const TEMPLATES: readonly Template[] = ['Aurora', 'Mono', 'Onyx'];
const JOB_COUNTS: readonly JobCount[] = [6, 12];

export default function GenerateScreen(): React.JSX.Element {
  const router = useRouter();
  const [template, setTemplate] = useState<Template>('Aurora');
  const [mode, setMode] = useState<Mode>('smart_picker');
  const [jobCount, setJobCount] = useState<JobCount>(6);
  const [previewSongs, setPreviewSongs] = useState<readonly Song[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);

  const fetchPreview = useCallback(async () => {
    if (mode !== 'smart_picker') {
      return;
    }

    setIsLoading(true);
    try {
      const preview = await getSmartPickerPreview(template);
      setPreviewSongs(preview.songs);
    } catch {
      setPreviewSongs([]);
    } finally {
      setIsLoading(false);
    }
  }, [template, mode]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  const handleReshuffle = async (): Promise<void> => {
    setIsLoading(true);
    try {
      const preview = await reshuffleSmartPicker(template);
      setPreviewSongs(preview.songs);
    } catch {
      Alert.alert('Error', 'Failed to reshuffle songs.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGenerate = async (): Promise<void> => {
    setIsGenerating(true);
    try {
      await generateJobs({
        template,
        mode,
        count: jobCount,
      });
      router.back();
    } catch {
      Alert.alert('Error', 'Failed to generate batch. Please try again.');
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {/* Template Selector */}
        <Text style={styles.sectionTitle}>Template</Text>
        <View style={styles.segmentedControl}>
          {TEMPLATES.map((t) => (
            <Pressable
              key={t}
              style={[styles.segment, template === t && styles.segmentActive]}
              onPress={() => setTemplate(t)}
            >
              <Text style={[styles.segmentText, template === t && styles.segmentTextActive]}>
                {t}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Mode Selector */}
        <Text style={styles.sectionTitle}>Mode</Text>
        <View style={styles.segmentedControl}>
          <Pressable
            style={[styles.segment, mode === 'smart_picker' && styles.segmentActive]}
            onPress={() => setMode('smart_picker')}
          >
            <Text
              style={[styles.segmentText, mode === 'smart_picker' && styles.segmentTextActive]}
            >
              Smart Picker
            </Text>
          </Pressable>
          <Pressable
            style={[styles.segment, mode === 'manual' && styles.segmentActive]}
            onPress={() => setMode('manual')}
          >
            <Text style={[styles.segmentText, mode === 'manual' && styles.segmentTextActive]}>
              Manual
            </Text>
          </Pressable>
        </View>

        {/* Job Count */}
        <Text style={styles.sectionTitle}>Job Count</Text>
        <View style={styles.segmentedControl}>
          {JOB_COUNTS.map((count) => (
            <Pressable
              key={count}
              style={[styles.segment, jobCount === count && styles.segmentActive]}
              onPress={() => setJobCount(count)}
            >
              <Text style={[styles.segmentText, jobCount === count && styles.segmentTextActive]}>
                {count}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Song Preview */}
        {mode === 'smart_picker' && (
          <View style={styles.previewSection}>
            <View style={styles.previewHeader}>
              <Text style={styles.sectionTitle}>Song Preview</Text>
              <Pressable style={styles.reshuffleButton} onPress={handleReshuffle}>
                <Text style={styles.reshuffleText}>Reshuffle</Text>
              </Pressable>
            </View>

            {isLoading ? (
              <ActivityIndicator
                size="small"
                color={Colors.accent.blue}
                style={styles.loadingIndicator}
              />
            ) : (
              previewSongs.map((song, index) => (
                <View key={song.id} style={styles.previewRow}>
                  <Text style={styles.previewIndex}>{index + 1}</Text>
                  <View style={styles.previewInfo}>
                    <Text style={styles.previewTitle} numberOfLines={1}>
                      {song.title}
                    </Text>
                    <Text style={styles.previewArtist} numberOfLines={1}>
                      {song.artist}
                    </Text>
                  </View>
                  <View style={styles.previewCount}>
                    <Text style={styles.previewCountText}>{song.use_count}</Text>
                  </View>
                </View>
              ))
            )}
          </View>
        )}
      </ScrollView>

      {/* Generate Button */}
      <View style={styles.footer}>
        <Pressable
          style={[styles.generateButton, isGenerating && styles.generateButtonDisabled]}
          onPress={handleGenerate}
          disabled={isGenerating}
        >
          {isGenerating ? (
            <ActivityIndicator size="small" color={Colors.bg.primary} />
          ) : (
            <Text style={styles.generateText}>Generate {jobCount} Jobs</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingBottom: 120,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 10,
    marginTop: 20,
  },
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: Colors.bg.surface,
    borderRadius: 10,
    padding: 3,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  segment: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  segmentActive: {
    backgroundColor: Colors.accent.blue,
  },
  segmentText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.secondary,
  },
  segmentTextActive: {
    color: Colors.bg.primary,
  },
  previewSection: {
    marginTop: 8,
  },
  previewHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  reshuffleButton: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    backgroundColor: Colors.bg.elevated,
    borderRadius: 8,
  },
  reshuffleText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.accent.blue,
  },
  loadingIndicator: {
    paddingVertical: 20,
  },
  previewRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  previewIndex: {
    width: 24,
    fontSize: 13,
    fontWeight: '600',
    color: Colors.text.disabled,
  },
  previewInfo: {
    flex: 1,
    marginRight: 10,
  },
  previewTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.text.primary,
  },
  previewArtist: {
    fontSize: 12,
    color: Colors.text.secondary,
    marginTop: 1,
  },
  previewCount: {
    backgroundColor: Colors.bg.elevated,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  previewCountText: {
    fontSize: 12,
    fontWeight: '700',
    color: Colors.text.secondary,
  },
  footer: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: 20,
    paddingBottom: 40,
    backgroundColor: Colors.bg.primary,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
  },
  generateButton: {
    backgroundColor: Colors.accent.blue,
    paddingVertical: 16,
    borderRadius: 14,
    alignItems: 'center',
  },
  generateButtonDisabled: {
    opacity: 0.6,
  },
  generateText: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.bg.primary,
  },
});
