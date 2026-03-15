import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  FlatList,
  Pressable,
  Modal,
  StyleSheet,
  RefreshControl,
  Alert,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { Colors } from '../../constants/colors';
import { getDatabase, addSong, deleteSong, Song } from '../../api/endpoints';
import SongRow from '../../components/SongRow';

export default function DatabaseScreen(): React.JSX.Element {
  const [songs, setSongs] = useState<readonly Song[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [isAddModalVisible, setIsAddModalVisible] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newArtist, setNewArtist] = useState('');
  const [isAdding, setIsAdding] = useState(false);

  const fetchSongs = useCallback(async () => {
    try {
      const response = await getDatabase();
      setSongs(response.songs);
    } catch {
      // Handled by connection hook
    }
  }, []);

  useEffect(() => {
    fetchSongs();
  }, [fetchSongs]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchSongs();
    setRefreshing(false);
  }, [fetchSongs]);

  const handleDelete = async (songId: number, songTitle: string): Promise<void> => {
    Alert.alert('Delete Song', `Are you sure you want to delete "${songTitle}"?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await deleteSong(songId);
            setSongs((prev) => prev.filter((s) => s.id !== songId));
          } catch {
            Alert.alert('Error', 'Failed to delete song.');
          }
        },
      },
    ]);
  };

  const handleAddSong = async (): Promise<void> => {
    const trimmedTitle = newTitle.trim();
    const trimmedArtist = newArtist.trim();

    if (!trimmedTitle || !trimmedArtist) {
      Alert.alert('Missing Info', 'Please enter both a title and artist.');
      return;
    }

    setIsAdding(true);
    try {
      const newSong = await addSong(trimmedTitle, trimmedArtist);
      setSongs((prev) => [...prev, newSong]);
      setNewTitle('');
      setNewArtist('');
      setIsAddModalVisible(false);
    } catch {
      Alert.alert('Error', 'Failed to add song.');
    } finally {
      setIsAdding(false);
    }
  };

  const filteredSongs = searchQuery.trim()
    ? songs.filter(
        (song) =>
          song.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          song.artist.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : songs;

  const renderItem = ({ item }: { item: Song }) => (
    <SongRow
      title={item.title}
      artist={item.artist}
      useCount={item.use_count}
      onDelete={() => handleDelete(item.id, item.title)}
    />
  );

  const renderEmpty = () => (
    <View style={styles.emptyContainer}>
      <Text style={styles.emptyTitle}>No Songs</Text>
      <Text style={styles.emptySubtitle}>Add songs to your database to get started</Text>
    </View>
  );

  return (
    <View style={styles.container}>
      {/* Search Bar */}
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search songs..."
          placeholderTextColor={Colors.text.disabled}
          value={searchQuery}
          onChangeText={setSearchQuery}
          autoCapitalize="none"
          autoCorrect={false}
        />
      </View>

      {/* Song List */}
      <FlatList
        data={filteredSongs}
        renderItem={renderItem}
        keyExtractor={(item) => String(item.id)}
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

      {/* Add Button */}
      <Pressable style={styles.addButton} onPress={() => setIsAddModalVisible(true)}>
        <Text style={styles.addButtonText}>+</Text>
      </Pressable>

      {/* Add Song Modal */}
      <Modal
        visible={isAddModalVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsAddModalVisible(false)}
      >
        <KeyboardAvoidingView
          style={styles.modalOverlay}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Add Song</Text>

            <Text style={styles.inputLabel}>Title</Text>
            <TextInput
              style={styles.textInput}
              value={newTitle}
              onChangeText={setNewTitle}
              placeholder="Song title"
              placeholderTextColor={Colors.text.disabled}
              autoFocus
            />

            <Text style={styles.inputLabel}>Artist</Text>
            <TextInput
              style={styles.textInput}
              value={newArtist}
              onChangeText={setNewArtist}
              placeholder="Artist name"
              placeholderTextColor={Colors.text.disabled}
            />

            <View style={styles.modalActions}>
              <Pressable
                style={styles.modalCancelButton}
                onPress={() => {
                  setIsAddModalVisible(false);
                  setNewTitle('');
                  setNewArtist('');
                }}
              >
                <Text style={styles.modalCancelText}>Cancel</Text>
              </Pressable>

              <Pressable
                style={[styles.modalAddButton, isAdding && styles.modalAddButtonDisabled]}
                onPress={handleAddSong}
                disabled={isAdding}
              >
                <Text style={styles.modalAddText}>{isAdding ? 'Adding...' : 'Add Song'}</Text>
              </Pressable>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
  searchContainer: {
    padding: 16,
    paddingBottom: 8,
  },
  searchInput: {
    backgroundColor: Colors.bg.surface,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 15,
    color: Colors.text.primary,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  listContent: {
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
  addButton: {
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
  addButtonText: {
    fontSize: 28,
    fontWeight: '600',
    color: Colors.bg.primary,
    marginTop: -2,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  modalContent: {
    backgroundColor: Colors.bg.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 24,
    paddingBottom: 40,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: Colors.text.primary,
    marginBottom: 20,
  },
  inputLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.text.secondary,
    marginBottom: 6,
    marginTop: 12,
  },
  textInput: {
    backgroundColor: Colors.bg.elevated,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: Colors.text.primary,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  modalActions: {
    flexDirection: 'row',
    marginTop: 24,
    gap: 12,
  },
  modalCancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
    backgroundColor: Colors.bg.elevated,
  },
  modalCancelText: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.text.secondary,
  },
  modalAddButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
    backgroundColor: Colors.accent.blue,
  },
  modalAddButtonDisabled: {
    opacity: 0.6,
  },
  modalAddText: {
    fontSize: 15,
    fontWeight: '700',
    color: Colors.bg.primary,
  },
});
