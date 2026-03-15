import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, FlatList, Pressable, StyleSheet, RefreshControl } from 'react-native';
import { useRouter } from 'expo-router';
import { Colors } from '../../constants/colors';
import { useJobStore } from '../../store/jobStore';
import { getJobs, JobEntry } from '../../api/endpoints';
import JobCard from '../../components/JobCard';

export default function JobsScreen(): React.JSX.Element {
  const router = useRouter();
  const jobs = useJobStore((s) => s.jobs);
  const setJobs = useJobStore((s) => s.setJobs);
  const [refreshing, setRefreshing] = useState(false);

  const fetchJobs = useCallback(async () => {
    try {
      const response = await getJobs();
      setJobs(response.jobs);
    } catch {
      // Handled by connection hook
    }
  }, [setJobs]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchJobs();
    setRefreshing(false);
  }, [fetchJobs]);

  const renderItem = ({ item }: { item: JobEntry }) => (
    <JobCard
      folder={item.folder}
      songTitle={item.song_title ?? item.folder}
      template={item.template}
      status={item.status}
    />
  );

  const renderEmpty = () => (
    <View style={styles.emptyContainer}>
      <Text style={styles.emptyTitle}>No Jobs Yet</Text>
      <Text style={styles.emptySubtitle}>Generate a batch to get started</Text>
    </View>
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={[...jobs]}
        renderItem={renderItem}
        keyExtractor={(item) => item.folder}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={renderEmpty}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={Colors.accent.blue}
          />
        }
      />

      <Pressable
        style={styles.fab}
        onPress={() => router.push('/(tabs)/generate')}
      >
        <Text style={styles.fabText}>+</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
  listContent: {
    padding: 16,
    paddingBottom: 100,
    flexGrow: 1,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 80,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.text.primary,
    marginBottom: 8,
  },
  emptySubtitle: {
    fontSize: 14,
    color: Colors.text.secondary,
  },
  fab: {
    position: 'absolute',
    bottom: 24,
    right: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: Colors.accent.blue,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: Colors.accent.blue,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
  },
  fabText: {
    fontSize: 28,
    fontWeight: '600',
    color: Colors.bg.primary,
    marginTop: -2,
  },
});
