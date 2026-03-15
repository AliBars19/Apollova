import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, Pressable, ScrollView, StyleSheet, RefreshControl } from 'react-native';
import { useRouter } from 'expo-router';
import { Colors } from '../../constants/colors';
import { useProgressStore } from '../../store/progressStore';
import { useJobStore } from '../../store/jobStore';
import { getStatus, getJobs, cancelJobs } from '../../api/endpoints';
import ProgressBar from '../../components/ProgressBar';
import StatusBadge from '../../components/StatusBadge';

interface AppStatus {
  readonly isRendering: boolean;
  readonly activeTemplate: string;
  readonly queueLength: number;
  readonly renderWatcherRunning: boolean;
}

export default function DashboardScreen(): React.JSX.Element {
  const router = useRouter();
  const percent = useProgressStore((s) => s.percent);
  const message = useProgressStore((s) => s.message);
  const batchResult = useProgressStore((s) => s.batchResult);
  const isProcessing = useJobStore((s) => s.isProcessing);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, jobsRes] = await Promise.all([getStatus(), getJobs()]);
      setStatus(statusRes);
      useJobStore.getState().setJobs(jobsRes.jobs);
      useJobStore.getState().setProcessing(jobsRes.isProcessing);
      useJobStore.getState().setBatchProgress(jobsRes.batchProgress);
    } catch {
      // Will be handled by connection hook
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  }, [fetchData]);

  const handleCancel = async (): Promise<void> => {
    try {
      await cancelJobs();
      await fetchData();
    } catch {
      // Error handled by interceptor
    }
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={Colors.accent.blue}
        />
      }
    >
      {/* Batch Progress Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Batch Progress</Text>
        <ProgressBar percent={percent} height={10} />
        <View style={styles.progressInfo}>
          <Text style={styles.progressPercent}>{Math.round(percent)}%</Text>
          <Text style={styles.progressMessage} numberOfLines={1}>
            {message || 'Idle'}
          </Text>
        </View>
        {isProcessing && (
          <Pressable style={styles.cancelButton} onPress={handleCancel}>
            <Text style={styles.cancelText}>Cancel Batch</Text>
          </Pressable>
        )}
      </View>

      {/* Last Batch Summary */}
      {batchResult !== null && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Last Batch</Text>
          <View style={styles.summaryRow}>
            <View style={styles.summaryItem}>
              <Text style={styles.summaryValue}>{batchResult.totalJobs}</Text>
              <Text style={styles.summaryLabel}>Total</Text>
            </View>
            <View style={styles.summaryItem}>
              <Text style={[styles.summaryValue, { color: Colors.status.green }]}>
                {batchResult.completed}
              </Text>
              <Text style={styles.summaryLabel}>Done</Text>
            </View>
            <View style={styles.summaryItem}>
              <Text style={[styles.summaryValue, { color: Colors.status.danger }]}>
                {batchResult.failed}
              </Text>
              <Text style={styles.summaryLabel}>Failed</Text>
            </View>
            <View style={styles.summaryItem}>
              <Text style={styles.summaryValue}>{batchResult.duration}</Text>
              <Text style={styles.summaryLabel}>Duration</Text>
            </View>
          </View>
        </View>
      )}

      {/* Quick Actions */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Quick Actions</Text>
        <View style={styles.actionsGrid}>
          <Pressable
            style={styles.actionButton}
            onPress={() => router.push('/(tabs)/generate')}
          >
            <Text style={styles.actionIcon}>+</Text>
            <Text style={styles.actionLabel}>Generate Batch</Text>
          </Pressable>
          <Pressable
            style={styles.actionButton}
            onPress={() => router.push('/(tabs)/render')}
          >
            <Text style={styles.actionIcon}>3x</Text>
            <Text style={styles.actionLabel}>Triple Render</Text>
          </Pressable>
        </View>
      </View>

      {/* Status Row */}
      <View style={styles.card}>
        <View style={styles.statusRow}>
          <Text style={styles.statusLabel}>Active Template</Text>
          {status !== null && (
            <View style={styles.templatePill}>
              <Text style={styles.templatePillText}>{status.activeTemplate}</Text>
            </View>
          )}
        </View>
        <View style={styles.statusRow}>
          <Text style={styles.statusLabel}>Render Watcher</Text>
          {status !== null && (
            <StatusBadge status={status.renderWatcherRunning ? 'running' : 'pending'} />
          )}
        </View>
        <View style={styles.statusRow}>
          <Text style={styles.statusLabel}>Queue</Text>
          <Text style={styles.queueCount}>{status?.queueLength ?? 0} jobs</Text>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
  content: {
    padding: 16,
    paddingBottom: 32,
  },
  card: {
    backgroundColor: Colors.bg.surface,
    borderRadius: 14,
    padding: 18,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.text.primary,
    marginBottom: 14,
  },
  progressInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
  },
  progressPercent: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.accent.blue,
    marginRight: 10,
  },
  progressMessage: {
    flex: 1,
    fontSize: 13,
    color: Colors.text.secondary,
  },
  cancelButton: {
    marginTop: 14,
    backgroundColor: Colors.status.danger + '22',
    paddingVertical: 10,
    borderRadius: 10,
    alignItems: 'center',
  },
  cancelText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.status.danger,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  summaryItem: {
    alignItems: 'center',
    flex: 1,
  },
  summaryValue: {
    fontSize: 20,
    fontWeight: '700',
    color: Colors.text.primary,
    marginBottom: 4,
  },
  summaryLabel: {
    fontSize: 12,
    color: Colors.text.secondary,
  },
  actionsGrid: {
    flexDirection: 'row',
    gap: 12,
  },
  actionButton: {
    flex: 1,
    backgroundColor: Colors.bg.elevated,
    borderRadius: 12,
    paddingVertical: 20,
    alignItems: 'center',
  },
  actionIcon: {
    fontSize: 22,
    fontWeight: '800',
    color: Colors.accent.blue,
    marginBottom: 6,
  },
  actionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.text.primary,
  },
  statusRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  statusLabel: {
    fontSize: 14,
    color: Colors.text.secondary,
  },
  templatePill: {
    backgroundColor: Colors.brand.primary,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 10,
  },
  templatePillText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.accent.blue,
  },
  queueCount: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.primary,
  },
});
